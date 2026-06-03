"""
routers/auth.py – Endpoints de autenticación (públicos).

POST /api/auth/register  →  Registrar nuevo paciente
POST /api/auth/login     →  Login con DNI y contraseña (retorna JWT)
"""

from fastapi import APIRouter

from app.models.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth_service import login_paciente, register_paciente

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    summary="Registrar nuevo paciente",
    description=(
        "Crea una nueva cuenta de paciente. "
        "Retorna un JWT de acceso para que el paciente quede autenticado de inmediato."
    ),
)
def register(data: RegisterRequest) -> TokenResponse:
    return register_paciente(data)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Iniciar sesión",
    description="Autentica al paciente con su DNI y contraseña. Retorna un JWT de acceso.",
)
def login(data: LoginRequest) -> TokenResponse:
    return login_paciente(data)
