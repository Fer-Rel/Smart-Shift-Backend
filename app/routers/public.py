"""
routers/public.py – Endpoints públicos de catálogo (sin autenticación).

GET /api/hospitales      →  Listar todos los hospitales
GET /api/especialidades  →  Listar todas las especialidades
"""

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.config import supabase_client
from app.models.schemas import EspecialidadResponse, HospitalResponse

router = APIRouter(prefix="/api", tags=["Catálogo Público"])


@router.get(
    "/hospitales",
    response_model=List[HospitalResponse],
    summary="Listar hospitales",
    description="Retorna la lista completa de hospitales registrados en el sistema.",
)
def list_hospitales() -> List[HospitalResponse]:
    result = (
        supabase_client.table("hospitales")
        .select("id_hospital, nombre, distrito, provincia, direccion, telefono")
        .order("nombre")
        .execute()
    )

    if result.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar los hospitales.",
        )

    return result.data


@router.get(
    "/especialidades",
    response_model=List[EspecialidadResponse],
    summary="Listar especialidades médicas",
    description="Retorna la lista completa de especialidades médicas disponibles.",
)
def list_especialidades() -> List[EspecialidadResponse]:
    result = (
        supabase_client.table("especialidades")
        .select("id_especialidad, nombre, descripcion")
        .order("nombre")
        .execute()
    )

    if result.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar las especialidades.",
        )

    return result.data
