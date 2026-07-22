"""
services/auth_service.py – Lógica de negocio de autenticación.

Responsabilidades:
  - Hashear contraseñas con bcrypt directamente.
  - Verificar contraseñas.
  - Generar JWT con python-jose.
  - Registrar nuevos pacientes en Supabase.
  - Autenticar usuarios (Pacientes y Médicos reales en Supabase, y cuentas Demo).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, status
from jose import jwt

from app.config import get_settings, supabase_client
from app.models.schemas import LoginRequest, RegisterRequest, TokenResponse

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# CUENTAS DEMO HARDCODEADAS (Solo como fallback de contingencia)
# ─────────────────────────────────────────────────────────────

# Contraseña en texto plano: "pass123"
_DEMO_PASS_HASH = bcrypt.hashpw(b"pass123", bcrypt.gensalt(rounds=4)).decode("utf-8")

DEMO_ACCOUNTS: dict[str, dict] = {
    "10000001": {
        "id_paciente": 10000001,
        "id_medico": 10000001,
        "dni": "10000001",
        "nombres": "Carlos",
        "apellidos": "Mendoza García",
        "email": "doctor1@demo.com",
        "password_hash": _DEMO_PASS_HASH,
        "rol": "doctor",
        "telefono": "999000001",
        "direccion": "Demo - Cardiología",
    },
    "10000002": {
        "id_paciente": 10000002,
        "id_medico": 10000002,
        "dni": "10000002",
        "nombres": "Ana",
        "apellidos": "Torres Vega",
        "email": "doctor2@demo.com",
        "password_hash": _DEMO_PASS_HASH,
        "rol": "doctor",
        "telefono": "999000002",
        "direccion": "Demo - Neurología",
    },
}


# ─────────────────────────────────────────────────────────────
# Utilidades de contraseña
# ─────────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """Hashea una contraseña usando bcrypt con factor de costo 12."""
    salt = bcrypt.gensalt(rounds=12)
    hashed: bytes = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica que `plain_password` corresponda a `hashed_password`."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# JWT
# ─────────────────────────────────────────────────────────────

def create_access_token(user_id: int, rol: str = "paciente") -> str:
    """
    Genera un JWT firmado con HS256.

    Payload:
      - sub: user_id (id_paciente o id_medico) como string
      - rol: "paciente" o "doctor"
      - exp: fecha de expiración (UTC)
      - iat: fecha de emisión (UTC)
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),
        "rol": rol,
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
    """Registra un nuevo paciente en la tabla `pacientes`."""
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
    access_token = create_access_token(id_paciente, rol="paciente")

    return TokenResponse(access_token=access_token)


# ─────────────────────────────────────────────────────────────
# Login (Soporta Pacientes, Médicos Reales y Cuentas Demo)
# ─────────────────────────────────────────────────────────────

def login_paciente(data: LoginRequest) -> TokenResponse:
    """
    Autentica un usuario (Paciente o Médico) usando DNI + contraseña.

    Flujo:
      1. Si coincide con una cuenta demo hardcodeada, retorna token de doctor demo.
      2. Busca en la tabla 'pacientes' por DNI. Si encuentra y coincide la clave, retorna JWT con rol="paciente".
      3. Si NO encuentra en 'pacientes', busca en la tabla 'medicos' por DNI. Si encuentra y coincide la clave, retorna JWT con rol="doctor".
      4. Si no coincide en ninguna tabla -> HTTP 401.
    """
    invalid_credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="DNI o contraseña incorrectos.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # ── 1. Verificar Cuentas Demo Hardcodeadas (Fallback) ──
    demo = DEMO_ACCOUNTS.get(data.dni)
    if demo:
        if verify_password(data.password, demo["password_hash"]):
            logger.info("Login demo exitoso para DNI=%s (rol=%s)", data.dni, demo.get("rol", "doctor"))
            return TokenResponse(
                access_token=create_access_token(
                    demo["id_paciente"],
                    rol=demo.get("rol", "doctor"),
                )
            )

    # ── 2. Buscar primero en la tabla 'pacientes' ──
    try:
        res_paciente = (
            supabase_client.table("pacientes")
            .select("id_paciente, password_hash")
            .eq("dni", data.dni)
            .limit(1)
            .execute()
        )
        pacientes_rows = res_paciente.data or []
    except Exception as exc:
        logger.warning("Error al consultar pacientes en Supabase: %s", exc)
        pacientes_rows = []

    if pacientes_rows:
        paciente = pacientes_rows[0]
        if verify_password(data.password, paciente["password_hash"]):
            logger.info("Login exitoso para PACIENTE DNI=%s", data.dni)
            return TokenResponse(
                access_token=create_access_token(paciente["id_paciente"], rol="paciente")
            )

    # ── 3. Si no se encontró en pacientes, buscar en la tabla 'medicos' ──
    try:
        res_medico = (
            supabase_client.table("medicos")
            .select("id_medico, password_hash")
            .eq("dni", data.dni)
            .limit(1)
            .execute()
        )
        medicos_rows = res_medico.data or []
    except Exception as exc:
        logger.warning("Error al consultar medicos en Supabase: %s", exc)
        medicos_rows = []

    if medicos_rows:
        medico = medicos_rows[0]
        if verify_password(data.password, medico["password_hash"]):
            logger.info("Login exitoso para MÉDICO DNI=%s", data.dni)
            return TokenResponse(
                access_token=create_access_token(medico["id_medico"], rol="doctor")
            )

    # ── 4. Ninguna coincidencia o credenciales inválidas ──
    raise invalid_credentials_exc
