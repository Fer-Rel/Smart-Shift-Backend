"""
services/auth_service.py – Lógica de negocio de autenticación.

Responsabilidades:
  - Hashear contraseñas con bcrypt directamente (sin passlib).
  - Verificar contraseñas.
  - Generar JWT con python-jose.
  - Registrar nuevos pacientes en Supabase.
  - Autenticar pacientes (login).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, status
from jose import jwt

from app.config import get_settings, supabase_client
from app.models.schemas import LoginRequest, RegisterRequest, TokenResponse


# ─────────────────────────────────────────────────────────────
# Utilidades de contraseña
# ─────────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """
    Hashea una contraseña usando bcrypt con factor de costo 12.
    Retorna el hash como string (decodificado de bytes a utf-8).
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed: bytes = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica que `plain_password` corresponda a `hashed_password`.
    Usa bcrypt.checkpw para comparación segura.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ─────────────────────────────────────────────────────────────
# JWT
# ─────────────────────────────────────────────────────────────

def create_access_token(id_paciente: int) -> str:
    """
    Genera un JWT firmado con HS256.

    Payload:
      - sub: id_paciente como string (convención JWT)
      - rol: "paciente"
      - exp: fecha de expiración (UTC)
      - iat: fecha de emisión (UTC)
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": str(id_paciente),
        "rol": "paciente",
        "iat": now,
        "exp": expire,
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


# ─────────────────────────────────────────────────────────────
# Registro
# ─────────────────────────────────────────────────────────────

def register_paciente(data: RegisterRequest) -> TokenResponse:
    """
    Registra un nuevo paciente en la tabla `pacientes`.

    Verificaciones previas:
      - El DNI no debe estar ya registrado.
      - El email no debe estar ya registrado.

    Tras el registro exitoso, retorna un JWT para que el
    paciente quede autenticado de inmediato.
    """
    # ── Verificar duplicado de DNI ────────────────────────
    existing_dni = (
        supabase_client.table("pacientes")
        .select("id_paciente")
        .eq("dni", data.dni)
        .execute()
    )
    if existing_dni.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un paciente registrado con ese DNI.",
        )

    # ── Verificar duplicado de email ──────────────────────
    existing_email = (
        supabase_client.table("pacientes")
        .select("id_paciente")
        .eq("email", str(data.email))
        .execute()
    )
    if existing_email.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un paciente registrado con ese email.",
        )

    # ── Insertar paciente ─────────────────────────────────
    new_paciente = {
        "dni": data.dni,
        "nombres": data.nombres,
        "apellidos": data.apellidos,
        "email": str(data.email),
        "password_hash": hash_password(data.password),
        "telefono": data.telefono,
        "fecha_nacimiento": data.fecha_nacimiento.isoformat() if data.fecha_nacimiento else None,
        "direccion": data.direccion,
    }

    result = (
        supabase_client.table("pacientes")
        .insert(new_paciente)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo registrar el paciente. Intente nuevamente.",
        )

    id_paciente: int = result.data[0]["id_paciente"]
    access_token = create_access_token(id_paciente)

    return TokenResponse(access_token=access_token)


# ─────────────────────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────────────────────

def login_paciente(data: LoginRequest) -> TokenResponse:
    """
    Autentica un paciente usando DNI + contraseña.

    Retorna un TokenResponse con el JWT si las credenciales son válidas.
    Siempre lanza HTTP 401 genérico para no revelar si el DNI existe.
    """
    invalid_credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="DNI o contraseña incorrectos.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Buscar paciente por DNI
    result = (
        supabase_client.table("pacientes")
        .select("id_paciente, password_hash")
        .eq("dni", data.dni)
        .single()
        .execute()
    )

    if not result.data:
        raise invalid_credentials_exc

    paciente = result.data

    # Verificar contraseña
    if not verify_password(data.password, paciente["password_hash"]):
        raise invalid_credentials_exc

    access_token = create_access_token(paciente["id_paciente"])
    return TokenResponse(access_token=access_token)
