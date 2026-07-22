"""
routers/paciente.py – Endpoints protegidos del flujo de paciente.

Todos los endpoints requieren JWT válido (dependencia get_current_paciente).

GET    /api/paciente/me                                     →  Perfil del paciente
GET    /api/paciente/medicos-disponibles?...                →  Médicos con slots libres
POST   /api/paciente/citas                                  →  Reservar cita
GET    /api/paciente/mis-citas                              →  Listar mis citas
DELETE /api/paciente/citas/{id_cita}                        →  Cancelar cita
GET    /api/paciente/citas/{id_cita}/qr                     →  Obtener código QR
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import supabase_client
from app.dependencies import get_current_paciente
from app.models.schemas import (
    CitaResponse,
    MedicoDisponibleResponse,
    PacientePublic,
    QRResponse,
    ReservarCitaRequest,
    SlotDisponible,
)

router = APIRouter(
    prefix="/api/paciente",
    tags=["Paciente"],
    dependencies=[Depends(get_current_paciente)],  # Protege TODAS las rutas del router
)


# ─────────────────────────────────────────────────────────────
# PERFIL
# ─────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=PacientePublic,
    summary="Obtener perfil del paciente autenticado",
)
def get_me(
    paciente: dict = Depends(get_current_paciente),
) -> PacientePublic:
    """Retorna los datos del paciente actualmente autenticado (sin password_hash)."""
    return PacientePublic(**paciente)


# ─────────────────────────────────────────────────────────────
# MÉDICOS DISPONIBLES
# ─────────────────────────────────────────────────────────────

def _generate_slots(hora_inicio: time, hora_fin: time) -> List[SlotDisponible]:
    """
    Genera bloques de 30 minutos entre hora_inicio y hora_fin.

    Ejemplo: 09:00 → 12:00  produce  09:00-09:30, 09:30-10:00, ... 11:30-12:00
    """
    slots: List[SlotDisponible] = []
    # Convertir times a minutos desde medianoche para aritmética simple
    start_minutes = hora_inicio.hour * 60 + hora_inicio.minute
    end_minutes = hora_fin.hour * 60 + hora_fin.minute

    current = start_minutes
    while current + 30 <= end_minutes:
        slot_start = time(current // 60, current % 60)
        slot_end_m = current + 30
        slot_end = time(slot_end_m // 60, slot_end_m % 60)
        slots.append(SlotDisponible(hora_inicio=slot_start, hora_fin=slot_end))
        current += 30

    return slots


@router.get(
    "/medicos-disponibles",
    response_model=List[MedicoDisponibleResponse],
    summary="Listar médicos disponibles con slots libres",
    description=(
        "Dado un hospital, especialidad y fecha, retorna los médicos que tienen "
        "disponibilidad ese día de la semana, junto con los slots de 30 minutos "
        "que aún no han sido reservados."
    ),
)
def get_medicos_disponibles(
    hospital_id: int = Query(..., alias="hospital_id", description="ID del hospital"),
    especialidad_id: int = Query(..., alias="especialidad_id", description="ID de la especialidad"),
    fecha: date = Query(..., description="Fecha deseada (YYYY-MM-DD)"),
    _paciente: dict = Depends(get_current_paciente),
) -> List[MedicoDisponibleResponse]:
    """
    Algoritmo de disponibilidad:

    1. Determinar el día de la semana ISO de `fecha` (1=Lunes … 7=Domingo).
    2. Obtener médicos del hospital y especialidad indicados.
    3. Para cada médico, obtener sus registros en `disponibilidad_doctores`
       cuyo `dia_semana` coincida y `activo = TRUE`.
    4. Para cada franja, generar slots de 30 min.
    5. Obtener citas con estado='reservada' para ese médico y fecha,
       y eliminar los slots que ya están ocupados.
    6. Solo incluir médicos que tengan al menos 1 slot disponible.
    """
    if fecha < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pueden consultar disponibilidades para fechas pasadas.",
        )

    # ── 1. Día de la semana (SQL 2=Lunes...6=Viernes / ISO 1=Lunes...7=Domingo) ──
    dia_semana_iso = fecha.isoweekday()  # 1=Mon ... 7=Sun
    dia_semana_sql = (fecha.isoweekday() % 7) + 1  # 2=Mon ... 6=Fri, 7=Sat, 1=Sun

    # ── 2. Médicos del hospital y especialidad ────────────
    medicos_result = (
        supabase_client.table("medicos")
        .select(
            "id_medico, nombres, apellidos, id_especialidad, id_hospital, descripcion"
        )
        .eq("id_hospital", hospital_id)
        .eq("id_especialidad", especialidad_id)
        .execute()
    )

    if not medicos_result.data:
        return []

    medicos = medicos_result.data
    medico_ids = [m["id_medico"] for m in medicos]

    # ── 3. Disponibilidades del día para esos médicos ─────
    disp_result = (
        supabase_client.table("disponibilidad_doctores")
        .select("id_medico, hora_inicio, hora_fin")
        .in_("id_medico", medico_ids)
        .in_("dia_semana", [dia_semana_sql, dia_semana_iso])
        .eq("activo", True)
        .execute()
    )

    # Agrupar franjas por médico
    franjas_por_medico: dict[int, list[dict]] = {}
    for d in disp_result.data or []:
        franjas_por_medico.setdefault(d["id_medico"], []).append(d)

    # ── 4 & 5. Citas reservadas para esa fecha ────────────
    citas_result = (
        supabase_client.table("citas")
        .select("id_medico, hora_cita")
        .in_("id_medico", medico_ids)
        .eq("fecha_cita", fecha.isoformat())
        .eq("estado", "reservada")
        .execute()
    )

    # Conjunto de (id_medico, hora_cita_str) reservadas
    reservadas: set[tuple[int, str]] = set()
    for c in citas_result.data or []:
        # hora_cita viene como "HH:MM:SS" desde Supabase
        hora_str = c["hora_cita"][:5]  # "HH:MM"
        reservadas.add((c["id_medico"], hora_str))

    # ── 6. Construir respuesta ────────────────────────────
    response: List[MedicoDisponibleResponse] = []
    
    # --- CONTROL CRÍTICO DE TIEMPO REAL ---
    hoy = date.today()
    hora_actual = datetime.now().time()

    for medico in medicos:
        mid = medico["id_medico"]
        franjas = franjas_por_medico.get(mid, [])

        slots_libres: List[SlotDisponible] = []
        for franja in franjas:
            # Parsear hora_inicio / hora_fin (vienen como "HH:MM:SS")
            hi = time.fromisoformat(franja["hora_inicio"])
            hf = time.fromisoformat(franja["hora_fin"])

            for slot in _generate_slots(hi, hf):
                # Si la fecha consultada es HOY y el bloque de 30 min ya pasó, se descarta
                if fecha == hoy and slot.hora_inicio <= hora_actual:
                    continue
                    
                slot_key = slot.hora_inicio.strftime("%H:%M")
                if (mid, slot_key) not in reservadas:
                    slots_libres.append(slot)

        if slots_libres:
            response.append(
                MedicoDisponibleResponse(
                    id_medico=mid,
                    nombres=medico["nombres"],
                    apellidos=medico["apellidos"],
                    id_especialidad=medico["id_especialidad"],
                    id_hospital=medico["id_hospital"],
                    descripcion=medico.get("descripcion"),
                    slots_disponibles=slots_libres,
                )
            )

    return response


# ─────────────────────────────────────────────────────────────
# RESERVAR CITA
# ─────────────────────────────────────────────────────────────

@router.post(
    "/citas",
    response_model=CitaResponse,
    status_code=201,
    summary="Reservar una cita médica",
    description=(
        "Reserva una cita para el paciente autenticado. "
        "Genera un código QR único de 8 caracteres. "
        "Falla con 409 si el slot ya está ocupado."
    ),
)
def reservar_cita(
    body: ReservarCitaRequest,
    paciente: dict = Depends(get_current_paciente),
) -> CitaResponse:
    id_paciente: int = paciente["id_paciente"]

    # ── Verificar que el médico existe ────────────────────
    medico_result = (
        supabase_client.table("medicos")
        .select("id_medico")
        .eq("id_medico", body.id_medico)
        .limit(1)
        .execute()
    )
    if not medico_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el médico con id={body.id_medico}.",
        )

    # ── Verificar disponibilidad del slot ─────────────────
    # El índice único parcial en BD ya garantiza la exclusividad,
    # pero verificamos antes para retornar un error más descriptivo.
    slot_ocupado = (
        supabase_client.table("citas")
        .select("id_cita")
        .eq("id_medico", body.id_medico)
        .eq("fecha_cita", body.fecha_cita.isoformat())
        .eq("hora_cita", body.hora_cita.isoformat())
        .eq("estado", "reservada")
        .execute()
    )
    if slot_ocupado.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario ya está reservado para el médico seleccionado.",
        )

    # ── Generar código QR único (UUID hex 8 chars) ────────
    codigo_qr = uuid.uuid4().hex[:8].upper()

    # ── Insertar cita ─────────────────────────────────────
    nueva_cita = {
        "id_paciente": id_paciente,
        "id_medico": body.id_medico,
        "fecha_cita": body.fecha_cita.isoformat(),
        "hora_cita": body.hora_cita.isoformat(),
        "estado": "reservada",
        "codigo_qr": codigo_qr,
        "canal_reserva": "web",
        "asistencia_marcada": False,
    }

    result = (
        supabase_client.table("citas")
        .insert(nueva_cita)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo registrar la cita. Intente nuevamente.",
        )

    return CitaResponse(**result.data[0])


# ─────────────────────────────────────────────────────────────
# LISTAR MIS CITAS
# ─────────────────────────────────────────────────────────────

@router.get(
    "/mis-citas",
    response_model=List[CitaResponse],
    summary="Listar citas del paciente autenticado",
    description="Retorna todas las citas del paciente ordenadas por fecha y hora descendente.",
)
def get_mis_citas(
    paciente: dict = Depends(get_current_paciente),
) -> List[CitaResponse]:
    result = (
        supabase_client.table("citas")
        .select(
            "id_cita, numero_turno, id_paciente, id_medico, fecha_cita, "
            "hora_cita, estado, codigo_qr, fecha_reserva, canal_reserva, "
            "asistencia_marcada, hora_llegada, atendido_en, "
            "medicos (nombres, apellidos, id_hospital, id_especialidad)"
        )
        .eq("id_paciente", paciente["id_paciente"])
        .order("fecha_cita", desc=True)
        .order("hora_cita", desc=True)
        .execute()
    )

    res_hospitales = supabase_client.table("hospitales").select("id_hospital, nombre").execute()
    mapa_hospitales = {h["id_hospital"]: h["nombre"] for h in res_hospitales.data} if res_hospitales.data else {}

    res_especialidades = supabase_client.table("especialidades").select("id_especialidad, nombre").execute()
    mapa_especialidades = {e["id_especialidad"]: e["nombre"] for e in res_especialidades.data} if res_especialidades.data else {}

    citas_aplanadas = []
    if result.data:
        for row in result.data:
            medico_rel = row.get("medicos")
            if isinstance(medico_rel, list):
                medico_data = medico_rel[0] if medico_rel else {}
            elif isinstance(medico_rel, dict):
                medico_data = medico_rel
            else:
                medico_data = {}

            id_hospital = medico_data.get("id_hospital")
            id_especialidad = medico_data.get("id_especialidad")

            nombre_hospital = mapa_hospitales.get(id_hospital, "Hospital no especificado")
            nombre_especialidad = mapa_especialidades.get(id_especialidad, "Especialidad no especificada")

            cita_formateada = {
                "id_cita": row.get("id_cita"),
                "numero_turno": row.get("numero_turno"),
                "id_paciente": row.get("id_paciente"),
                "id_medico": row.get("id_medico"),
                "fecha_cita": row.get("fecha_cita"),
                "hora_cita": row.get("hora_cita"),
                "estado": row.get("estado"),
                "codigo_qr": row.get("codigo_qr"),
                "fecha_reserva": row.get("fecha_reserva"),
                "canal_reserva": row.get("canal_reserva"),
                "asistencia_marcada": row.get("asistencia_marcada", False),
                "hora_llegada": row.get("hora_llegada"),
                "atendido_en": row.get("atendido_en"),
                "nombres": medico_data.get("nombres", "Médico"),
                "apellidos": medico_data.get("apellidos", "No Especificado"),
                "especialidad": nombre_especialidad,
                "hospital": nombre_hospital,
            }
            citas_aplanadas.append(cita_formateada)

    return citas_aplanadas


# ─────────────────────────────────────────────────────────────
# CANCELAR CITA
# ─────────────────────────────────────────────────────────────

@router.delete(
    "/citas/{id_cita}",
    status_code=200,
    summary="Cancelar una cita (soft delete)",
    description=(
        "Aplica un borrado lógico (soft delete) sobre la cita: cambia su estado a "
        "'cancelada' sin eliminar el registro de la base de datos, preservando así "
        "el historial completo del paciente.\n\n"
        "Condiciones para poder cancelar:\n"
        "  - La cita debe pertenecer al paciente autenticado.\n"
        "  - El estado actual debe ser 'reservada'.\n"
        "  - Deben faltar más de 24 horas para la fecha y hora de la cita."
    ),
)
def cancelar_cita(
    id_cita: int,
    paciente: dict = Depends(get_current_paciente),
) -> dict:
    """
    Soft delete: actualiza `estado` → 'cancelada'. El registro permanece en BD
    para mantener el historial del paciente y la integridad del sistema de turnos.
    """
    # ── 1. Buscar la cita ─────────────────────────────────
    result = (
        supabase_client.table("citas")
        .select("id_cita, id_paciente, fecha_cita, hora_cita, estado")
        .eq("id_cita", id_cita)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cita no encontrada.",
        )

    cita = result.data[0]

    # ── 2. Verificar que pertenece al paciente autenticado ─
    if cita["id_paciente"] != paciente["id_paciente"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para cancelar esta cita.",
        )

    # ── 3. Verificar que el estado permite cancelación ────
    if cita["estado"] != "reservada":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede cancelar una cita con estado '{cita['estado']}'.",
        )

    # ── 4. Verificar que faltan más de 24 horas ───────────
    # Se combina fecha + hora de la cita en UTC para comparar con el instante actual.
    fecha_cita = date.fromisoformat(cita["fecha_cita"])
    hora_cita  = time.fromisoformat(cita["hora_cita"])
    dt_cita    = datetime.combine(fecha_cita, hora_cita, tzinfo=timezone.utc)
    ahora_utc  = datetime.now(timezone.utc)

    if (dt_cita - ahora_utc) <= timedelta(hours=24):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden cancelar citas con más de 24 horas de anticipación.",
        )

    # ── 5. Soft delete: update estado → 'cancelada' ───────
    # No se ejecuta .delete(). El registro se conserva en la tabla `citas`
    # para mantener el historial del paciente y las métricas del sistema.
    supabase_client.table("citas").update({"estado": "cancelada"}).eq(
        "id_cita", id_cita
    ).execute()

    return {
        "detail": "Cita cancelada exitosamente.",
        "id_cita": id_cita,
        "estado": "cancelada",
    }


# ─────────────────────────────────────────────────────────────
# CÓDIGO QR
# ─────────────────────────────────────────────────────────────

@router.get(
    "/citas/{id_cita}/qr",
    response_model=QRResponse,
    summary="Obtener código QR de una cita",
    description="Retorna el código QR de la cita junto con los datos relevantes.",
)
def get_qr_cita(
    id_cita: int,
    paciente: dict = Depends(get_current_paciente),
) -> QRResponse:
    result = (
        supabase_client.table("citas")
        .select("id_cita, id_paciente, fecha_cita, hora_cita, estado, codigo_qr")
        .eq("id_cita", id_cita)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cita no encontrada.",
        )

    cita = result.data[0]

    # ── Verificar propiedad ───────────────────────────────
    if cita["id_paciente"] != paciente["id_paciente"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver esta cita.",
        )

    if not cita.get("codigo_qr"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Esta cita no tiene un código QR asociado.",
        )

    return QRResponse(
        id_cita=cita["id_cita"],
        codigo_qr=cita["codigo_qr"],
        fecha_cita=date.fromisoformat(cita["fecha_cita"]),
        hora_cita=time.fromisoformat(cita["hora_cita"]),
        estado=cita["estado"],
    )
