from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from google import genai
from google.genai import types
import logging
from datetime import datetime, timedelta

# 1. Configuración limpia de Logs para producción
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Chat"])

# 2. Importaciones de configuración de tu app
from app.config import get_settings, supabase_client
settings = get_settings()

# Validación segura de la API Key de Gemini
GEMINI_API_KEY = getattr(settings, "GEMINI_API_KEY", None)
if not GEMINI_API_KEY:
    logger.warning("⚠️ El token GEMINI_API_KEY no está configurado en las variables de entorno.")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

class ChatRequest(BaseModel):
    message: str
    hospitalId: Optional[int] = None
    especialidadId: Optional[int] = None
    fecha: Optional[str] = None


def obtener_proxima_fecha(dia_semana_bd: int) -> str:
    """
    Calcula la fecha exacta del calendario para el día de la semana.
    Si el día de atención es HOY, devuelve la fecha de HOY en lugar de saltar 7 días.
    """
    hoy = datetime.now().date()
    dia_actual_semana = hoy.isoweekday()  # 1=Lunes, 7=Domingo
    
    dias_a_sumar = (dia_semana_bd - dia_actual_semana) % 7
    
    proxima_fecha = hoy + timedelta(days=dias_a_sumar)
    return proxima_fecha.strftime("%d/%m/%Y")


def buscar_disponibilidad_global(hospital_id: Optional[int] = None, especialidad_id: Optional[int] = None) -> str:
    """
    Consulta la disponibilidad filtrando dinámicamente por hospital y especialidad
    según lo que el usuario tenga seleccionado en el formulario del Frontend.
    """
    try:
        # Armamos la query base de médicos aplicando filtros si existen en el payload
        query_medicos = supabase_client.table("medicos").select("id_medico, nombres, apellidos, id_hospital, id_especialidad")
        
        if hospital_id:
            query_medicos = query_medicos.eq("id_hospital", hospital_id)
        if especialidad_id:
            query_medicos = query_medicos.eq("id_especialidad", especialidad_id)
            
        medicos_res = query_medicos.execute()

        if not medicos_res.data:
            return "📭 No hay médicos disponibles para la combinación de hospital o especialidad seleccionada."

        # Extraemos los IDs de los médicos que pasaron el filtro para traer solo sus horarios
        ids_medicos_filtrados = [m["id_medico"] for m in medicos_res.data]

        # Consultas secundarias indexadas
        dispo_res = supabase_client.table("disponibilidad_doctores") \
            .select("id_medico, dia_semana, hora_inicio, hora_fin, activo") \
            .eq("activo", True) \
            .in_("id_medico", ids_medicos_filtrados) \
            .execute()
            
        hosp_res = supabase_client.table("hospitales").select("id_hospital, nombre, distrito").execute()
        esp_res = supabase_client.table("especialidades").select("id_especialidad, nombre").execute()

        if not dispo_res.data:
            return "⚠️ Todos los turnos para los médicos seleccionados están inactivos o no tienen horarios asignados."

        hospitales = {h["id_hospital"]: h for h in (hosp_res.data or [])}
        especialidades = {e["id_especialidad"]: e for e in (esp_res.data or [])}

        dispo_por_medico = {}
        for d in dispo_res.data:
            id_med = d.get("id_medico")
            if id_med not in dispo_por_medico:
                dispo_por_medico[id_med] = []
            dispo_por_medico[id_med].append(d)

        dias_mapeo = {1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves", 5: "Viernes", 6: "Sábado", 7: "Domingo"}

        # --- CONTROL CRÍTICO DE TIEMPO REAL ---
        ahora = datetime.now()
        hoy_str = ahora.date().strftime("%d/%m/%Y")
        hora_actual_str = ahora.strftime("%H:%M")

        contexto = "📋 HORARIOS DE ATENCIÓN REALES CON FECHA:\n\n"
        hay_datos = False

        for med in medicos_res.data:
            id_med = med.get("id_medico")
            slots = dispo_por_medico.get(id_med, [])
            if not slots:
                continue
                
            nombre_doc = f"Dr/a. {med.get('nombres', '')} {med.get('apellidos', '')}".strip()
            hospital = hospitales.get(med.get("id_hospital"), {}).get("nombre", "Hospital no especificado")
            distrito = hospitales.get(med.get("id_hospital"), {}).get("distrito", "")
            especialidad = especialidades.get(med.get("id_especialidad"), {}).get("nombre", "General")

            bloques_medico_contexto = ""
            slots.sort(key=lambda x: x.get("dia_semana", 0))
            
            for slot in slots:
                dia_raw = slot.get("dia_semana")
                dia_nombre = dias_mapeo.get(dia_raw, f"Día {dia_raw}")
                fecha_concreta = obtener_proxima_fecha(dia_raw) 
                
                h_inicio = slot.get("hora_inicio", "")[:5]
                h_fin = slot.get("hora_fin", "")[:5]
                
                # Si la fecha calculada es HOY, filtramos que el bloque no haya pasado o esté por terminar
                if fecha_concreta == hoy_str and h_fin <= hora_actual_str:
                    continue

                bloques_medico_contexto += f"      - {dia_nombre} ({fecha_concreta}) de {h_inicio} a {h_fin}\n"

            # Si el médico tiene bloques válidos tras el filtro temporal, lo añadimos al contexto
            if bloques_medico_contexto:
                hay_datos = True
                contexto += f"👨‍⚕️ **{nombre_doc}**\n"
                contexto += f"   📍 Especialidad: {especialidad}\n"
                contexto += f"   🏥 Hospital: {hospital} ({distrito})\n"
                contexto += f"   🕐 Próximos Turnos Disponibles:\n"
                contexto += bloques_medico_contexto
                contexto += "\n"

        if not hay_datos:
            return "📭 En este momento ningún médico filtrado tiene horarios activos en el sistema."

        return contexto

    except Exception as e:
        logger.error(f"Error crítico en buscar_disponibilidad_global: {str(e)}")
        return "⚠️ MANTENIMIENTO: No se puede acceder a la base de datos de horarios en este microsegundo."


@router.post("")
def conversar_con_chatbot(payload: ChatRequest):
    if not client:
        return {
            "response": "⚠️ El asistente de Smart-Shift está fuera de línea temporalmente debido a un problema con las credenciales."
        }

    try:
        # Pasamos los parámetros que vienen desde los selectors del frontend
        contexto_sistema = buscar_disponibilidad_global(
            hospital_id=payload.hospitalId,
            especialidad_id=payload.especialidadId
        )

        SYSTEM_INSTRUCTION = f"""
Eres un asistente de atención al paciente de Smart-Shift, una plataforma de gestión de citas médicas.

DATOS REALES DEL SISTEMA (Horarios filtrados por la selección actual del usuario):
{contexto_sistema}

REGLAS ESTRICTAS DE COMPORTAMIENTO:
1. **Saludos**: Si el usuario te saluda ("hola", "buenos días", etc.), responde con un saludo breve y muy amable, indicándole que estás listo para informarle sobre las especialidades y horarios de los médicos.
2. **Consultas de disponibilidad**: Cuando informes sobre los horarios de un médico, debes incluir OBLIGATORIAMENTE el día de la semana y la fecha entre paréntesis que viene en los datos (por ejemplo: "Martes (09/06/2026)"). No inventes fechas que no estén explícitamente escritas arriba. Confía en la lista ya filtrada.
3. **NO HAGAS RESERVAS**: Está estrictamente prohibido intentar agendar la cita o pedir confirmaciones de horarios. Da la información y termina cordialmente.
4. **Si no hay datos**: Si el contexto indica que no hay médicos o devuelve un aviso de mantenimiento, responde textualmente: "Lo siento, en este momento no hay médicos registrados para esa consulta en Smart-Shift. ¿Te gustaría consultar otra especialidad o intentar más tarde?"
5. **Respuestas cortas**: Ve directo al grano sin textos largos.
"""

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=payload.message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.1,
                max_output_tokens=1024,
            )
        )

        return {"response": response.text}

    except Exception as e:
        logger.error(f"Error en endpoint POST /api/chat: {str(e)}")
        return {
            "response": "📋 El sistema de horarios está actualizándose. Por favor, escribe nuevamente tu consulta en unos momentos."
        }