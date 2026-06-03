"""
dependencies.py – Dependencias reutilizables de FastAPI.

Exporta:
  - get_current_paciente: dependencia que valida el JWT del header
    Authorization: Bearer <token> y retorna el dict del paciente desde BD.
    Lanza HTTP 401 si el token falta, expiró o es inválido.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from app.config import get_settings, supabase_client

# HTTPBearer extrae automáticamente el token del header Authorization: Bearer …
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_paciente(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """
    Dependencia de autenticación para rutas protegidas.

    Flujo:
      1. Verifica que el header Authorization esté presente.
      2. Decodifica y valida la firma/expiración del JWT.
      3. Extrae `sub` (id_paciente) del payload.
      4. Consulta el paciente en Supabase y lo retorna.
      5. En cualquier error → HTTP 401.
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

    # Validar que sea un token de paciente
    id_paciente: str | None = payload.get("sub")
    rol: str | None = payload.get("rol")

    if id_paciente is None or rol != "paciente":
        raise credentials_exception

    # Buscar paciente en la base de datos
    try:
        result = (
            supabase_client.table("pacientes")
            .select(
                "id_paciente, dni, nombres, apellidos, telefono, "
                "fecha_nacimiento, direccion, email, created_at"
            )
            .eq("id_paciente", int(id_paciente))
            .single()
            .execute()
        )
    except Exception:
        raise credentials_exception

    if not result.data:
        raise credentials_exception

    return result.data
