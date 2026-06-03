"""
main.py – Punto de entrada de la aplicación FastAPI "Smart Shift".

Responsabilidades:
  - Crear la instancia de FastAPI con metadatos completos.
  - Configurar el middleware CORS con orígenes explícitos para producción y local.
  - Registrar todos los routers.
  - Exponer un health-check en /health.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, paciente, public

# ─────────────────────────────────────────────────────────────
# Instancia de la aplicación
# ─────────────────────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title="Smart Shift API",
    description=(
        "Backend para el sistema de gestión de citas médicas **Smart Shift**. "
        "Cubre el flujo completo del paciente: registro, autenticación y reserva de citas."
    ),
    version="1.0.0",
    contact={
        "name": "Equipo Smart Shift",
        "email": "soporte@smartshift.pe",
    },
    license_info={
        "name": "MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─────────────────────────────────────────────────────────────
# Middleware CORS
# ─────────────────────────────────────────────────────────────

# Definimos explícitamente los orígenes permitidos para evitar el choque 
# entre allow_credentials=True y el asterisco genérico ["*"]
origenes_permitidos = [
    "http://localhost:5173",                     # Tu entorno local (Vite)
    "https://smart-shift-frontend.vercel.app",   # Tu dominio oficial en Vercel
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origenes_permitidos,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(public.router)
app.include_router(paciente.router)

# ─────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["Sistema"], summary="Health check")
def health_check() -> dict:
    """Verifica que el servidor esté operativo."""
    return {"status": "ok", "service": "smart-shift-backend"}