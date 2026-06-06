"""
models/schemas.py – Esquemas Pydantic (request / response).

Todos los modelos siguen la convención:
  - *Request  → payload de entrada (body)
  - *Response → payload de salida (body)
  - *Public   → subconjunto reducido de datos sensibles para respuestas

Las validaciones estrictas (DNI de 8 dígitos, email, etc.) se realizan
aquí para que FastAPI retorne errores 422 antes de llegar a la lógica
de negocio.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, EmailStr, field_validator, model_validator


# ─────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    dni: str
    nombres: str
    apellidos: str
    email: EmailStr
    password: str
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    direccion: Optional[str] = None

    @field_validator("dni")
    @classmethod
    def dni_must_be_8_digits(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{8}", v):
            raise ValueError("El DNI debe contener exactamente 8 dígitos numéricos.")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres.")
        return v

    @field_validator("nombres", "apellidos")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Este campo no puede estar vacío.")
        return v


class LoginRequest(BaseModel):
    dni: str
    password: str

    @field_validator("dni")
    @classmethod
    def dni_must_be_8_digits(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{8}", v):
            raise ValueError("El DNI debe contener exactamente 8 dígitos numéricos.")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─────────────────────────────────────────────────────────────
# PACIENTE
# ─────────────────────────────────────────────────────────────

class PacientePublic(BaseModel):
    """Datos del paciente sin información sensible (sin password_hash)."""
    id_paciente: int
    dni: str
    nombres: str
    apellidos: str
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    direccion: Optional[str] = None
    email: str
    created_at: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────
# HOSPITALES & ESPECIALIDADES
# ─────────────────────────────────────────────────────────────

class HospitalResponse(BaseModel):
    id_hospital: int
    nombre: str
    distrito: str
    provincia: str
    direccion: str
    telefono: Optional[str] = None


class EspecialidadResponse(BaseModel):
    id_especialidad: int
    nombre: str
    descripcion: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# MÉDICOS DISPONIBLES
# ─────────────────────────────────────────────────────────────

class SlotDisponible(BaseModel):
    """Un bloque de 30 minutos disponible para agendar."""
    hora_inicio: time
    hora_fin: time


class MedicoDisponibleResponse(BaseModel):
    id_medico: int
    nombres: str
    apellidos: str
    id_especialidad: int
    id_hospital: int
    descripcion: Optional[str] = None
    slots_disponibles: List[SlotDisponible]


# ─────────────────────────────────────────────────────────────
# CITAS
# ─────────────────────────────────────────────────────────────

class ReservarCitaRequest(BaseModel):
    id_medico: int
    fecha_cita: date
    hora_cita: time

    @field_validator("fecha_cita")
    @classmethod
    def fecha_no_en_pasado(cls, v: date) -> date:
        from datetime import date as date_cls
        if v < date_cls.today():
            raise ValueError("No se puede reservar una cita en una fecha pasada.")
        return v


class CitaResponse(BaseModel):
    id_cita: int
    numero_turno: Optional[int] = None
    id_paciente: int
    id_medico: int
    fecha_cita: date
    hora_cita: time
    estado: str
    codigo_qr: Optional[str] = None
    fecha_reserva: Optional[datetime] = None
    canal_reserva: Optional[str] = None
    asistencia_marcada: bool = False
    hora_llegada: Optional[datetime] = None
    atendido_en: Optional[datetime] = None
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    especialidad: Optional[str] = None
    hospital: Optional[str] = None


class QRResponse(BaseModel):
    id_cita: int
    codigo_qr: str
    fecha_cita: date
    hora_cita: time
    estado: str
