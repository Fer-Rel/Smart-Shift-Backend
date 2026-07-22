"""
dependencies.py – Dependencias reutilizables de FastAPI.

Exporta:
  - get_current_paciente: dependencia que valida el JWT del header
    Authorization: Bearer <token> y retorna los datos del paciente o médico desde BD.
    Lanza HTTP 401 si el token falta, expiró o es inválido.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from app.config import get_settings, supabase_client

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_paciente(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """
    Dependencia de autenticación para rutas protegidas.

    Decodifica el JWT y retorna los datos de la tabla correspondiente:
      - Si rol == "doctor" -> Busca en 'medicos' o retorna demo doctor.
      - Si rol == "paciente" -> Busca en 'pacientes' o retorna demo paciente.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado o token inválido.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    token = credentials.credentials
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token ha expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise credentials_exception

    id_user_str: str | None = payload.get("sub")
    rol: str | None = payload.get("rol", "paciente")

    if id_user_str is None:
        raise credentials_exception

    user_id = int(id_user_str)

    # ── Cuentas Demo Hardcodeadas (>= 10000001) ──
    if user_id >= 10000001:
        from app.services.auth_service import DEMO_ACCOUNTS
        demo = DEMO_ACCOUNTS.get(str(user_id))
        if demo:
            return {
                "id_paciente": demo["id_paciente"],
                "id_medico": demo.get("id_medico", demo["id_paciente"]),
                "dni": demo["dni"],
                "nombres": demo["nombres"],
                "apellidos": demo["apellidos"],
                "email": demo["email"],
                "telefono": demo.get("telefono"),
                "fecha_nacimiento": None,
                "direccion": demo.get("direccion"),
                "created_at": None,
                "rol": demo.get("rol", "doctor"),
            }
        raise credentials_exception

    # ── Si el ROL es "doctor", buscar en la tabla 'medicos' ──
    if rol == "doctor":
        try:
            res_med = (
                supabase_client.table("medicos")
                .select("id_medico, dni, nombres, apellidos, telefono, email, id_especialidad, id_hospital, descripcion")
                .eq("id_medico", user_id)
                .limit(1)
                .execute()
            )
            rows_med = res_med.data or []
        except Exception:
            raise credentials_exception

        if not rows_med:
            raise credentials_exception

        medico = rows_med[0]
        medico["id_paciente"] = medico["id_medico"]
        medico["rol"] = "doctor"
        return medico

    # ── Si el ROL es "paciente", buscar en la tabla 'pacientes' ──
    try:
        res_pac = (
            supabase_client.table("pacientes")
            .select(
                "id_paciente, dni, nombres, apellidos, telefono, "
                "fecha_nacimiento, direccion, email, created_at"
            )
            .eq("id_paciente", user_id)
            .limit(1)
            .execute()
        )
        rows_pac = res_pac.data or []
    except Exception:
        raise credentials_exception

    if not rows_pac:
        raise credentials_exception

    paciente = rows_pac[0]
    paciente["rol"] = "paciente"
    return paciente
