"""
Test E2E completo para Smart Shift Backend.
Ejecutar desde el directorio raiz del proyecto.
"""
import httpx
import sys
from datetime import date, timedelta
from app.config import supabase_client

BASE = "http://127.0.0.1:8000"
PASS_LIST = []
FAIL_LIST = []


def check(label, resp, expected):
    ok = resp.status_code == expected
    sym = "OK  " if ok else "FAIL"
    print(f"  [{sym}] {label} -> HTTP {resp.status_code}", end="")
    if not ok:
        try:
            print(f"  (esperado {expected}) | {resp.json()}")
        except Exception:
            print(f"  | {resp.text[:200]}")
    else:
        print()
    (PASS_LIST if ok else FAIL_LIST).append(label)
    return resp


# ─────────────────────────────────────────────────────────
print()
print("=== 1. HEALTH CHECK ===")
r = check("GET /health", httpx.get(f"{BASE}/health"), 200)
data = r.json()
print(f"      {data}")

# ─────────────────────────────────────────────────────────
print()
print("=== 2. CATÁLOGOS PÚBLICOS ===")
r = check("GET /api/hospitales", httpx.get(f"{BASE}/api/hospitales"), 200)
hosps = r.json()
nombres_hosps = [h["nombre"] for h in hosps]
print(f"      {len(hosps)} hospitales: {nombres_hosps}")

r = check("GET /api/especialidades", httpx.get(f"{BASE}/api/especialidades"), 200)
esps = r.json()
nombres_esps = [e["nombre"] for e in esps]
print(f"      {len(esps)} especialidades: {nombres_esps}")

# ─────────────────────────────────────────────────────────
print()
print("=== 3. AUTENTICACIÓN ===")
DNI   = "87654321"
EMAIL = "ana.garcia.smartshift@mailtest.com"
PWD   = "SecurePass123"

# Limpiar paciente de prueba si existe (idempotente)
supabase_client.table("pacientes").delete().eq("dni", DNI).execute()
supabase_client.table("pacientes").delete().eq("email", EMAIL).execute()

reg = {
    "dni": DNI, "nombres": "Ana", "apellidos": "Garcia Lopez",
    "email": EMAIL, "password": PWD, "telefono": "912345678",
    "fecha_nacimiento": "1995-03-15", "direccion": "Av. Prueba 123, Lima"
}

r = check("POST /api/auth/register (nuevo)", httpx.post(f"{BASE}/api/auth/register", json=reg), 201)
token = r.json().get("access_token") if r.status_code == 201 else None
if token:
    print(f"      JWT recibido: {token[:55]}...")

check("POST /api/auth/register (DNI duplicado -> 409)", httpx.post(f"{BASE}/api/auth/register", json=reg), 409)

bad_dni = {**reg, "dni": "123", "email": "otro@test.com"}
check("POST /api/auth/register (DNI inválido -> 422)", httpx.post(f"{BASE}/api/auth/register", json=bad_dni), 422)

bad_pass = {**reg, "dni": "11111111", "email": "y@y.com", "password": "abc"}
check("POST /api/auth/register (pass corta -> 422)", httpx.post(f"{BASE}/api/auth/register", json=bad_pass), 422)

r = check("POST /api/auth/login (correcto)", httpx.post(f"{BASE}/api/auth/login", json={"dni": DNI, "password": PWD}), 200)
if r.status_code == 200:
    token = r.json().get("access_token")
    print(f"      Token login OK: {token[:55]}...")

check("POST /api/auth/login (contraseña mala -> 401)", httpx.post(f"{BASE}/api/auth/login", json={"dni": DNI, "password": "mala"}), 401)
check("POST /api/auth/login (DNI inexistente -> 401)", httpx.post(f"{BASE}/api/auth/login", json={"dni": "00000000", "password": PWD}), 401)

# ─────────────────────────────────────────────────────────
print()
print("=== 4. RUTAS PROTEGIDAS ===")
H = {"Authorization": f"Bearer {token}"}

r = check("GET /api/paciente/me", httpx.get(f"{BASE}/api/paciente/me", headers=H), 200)
if r.status_code == 200:
    p = r.json()
    nombre_completo = f"{p['nombres']} {p['apellidos']}"
    print(f"      Paciente: {nombre_completo} | DNI: {p['dni']} | email: {p['email']}")

check("GET /api/paciente/me (sin token -> 401)", httpx.get(f"{BASE}/api/paciente/me"), 401)
check("GET /api/paciente/me (token falso -> 401)",
      httpx.get(f"{BASE}/api/paciente/me", headers={"Authorization": "Bearer fake.jwt.token"}), 401)

r = check("GET /api/paciente/mis-citas (lista vacía)", httpx.get(f"{BASE}/api/paciente/mis-citas", headers=H), 200)
print(f"      {len(r.json())} cita(s) iniciales")

# ─────────────────────────────────────────────────────────
print()
print("=== 5. MÉDICOS DISPONIBLES ===")
# Medico 3: hospital=3, especialidad=3, disponible mar-sab (dias ISO 2-6)
today = date.today()
dias_hasta_martes = (1 - today.weekday()) % 7 or 7   # weekday 1 = martes
proximo_martes = today + timedelta(days=dias_hasta_martes)

params = {"hospital_id": 3, "especialidad_id": 3, "fecha": proximo_martes.isoformat()}
dia_iso = proximo_martes.isoweekday()
print(f"      Buscando: hospital=3, especialidad=3, fecha={proximo_martes} (dia ISO={dia_iso})")

r = check("GET /api/paciente/medicos-disponibles", httpx.get(f"{BASE}/api/paciente/medicos-disponibles", headers=H, params=params), 200)
mds = r.json()
print(f"      {len(mds)} médico(s) con disponibilidad")

id_cita = None
if mds:
    md = mds[0]
    slots_count = len(md["slots_disponibles"])
    nombre_med = f"{md['nombres']} {md['apellidos']}"
    print(f"      Dr. {nombre_med} -> {slots_count} slots")
    horas_slots = [s["hora_inicio"] for s in md["slots_disponibles"][:6]]
    print(f"      Slots: {horas_slots}{'...' if slots_count > 6 else ''}")

    # ─────────────────────────────────────────────────────────
    print()
    print("=== 6. RESERVAR CITA ===")
    slot = md["slots_disponibles"][0]
    reserva = {
        "id_medico": md["id_medico"],
        "fecha_cita": proximo_martes.isoformat(),
        "hora_cita": slot["hora_inicio"]
    }
    r = check("POST /api/paciente/citas (reservar)", httpx.post(f"{BASE}/api/paciente/citas", json=reserva, headers=H), 201)
    if r.status_code == 201:
        cita = r.json()
        id_cita = cita["id_cita"]
        qr_code = cita["codigo_qr"]
        estado  = cita["estado"]
        print(f"      id_cita={id_cita} | estado={estado} | codigo_qr={qr_code}")

    check("POST /api/paciente/citas (slot duplicado -> 409)",
          httpx.post(f"{BASE}/api/paciente/citas", json=reserva, headers=H), 409)

    bad_fecha = {**reserva, "fecha_cita": "2020-01-01"}
    check("POST /api/paciente/citas (fecha pasada -> 422)",
          httpx.post(f"{BASE}/api/paciente/citas", json=bad_fecha, headers=H), 422)

    # Verificar que el slot reservado ya no aparece en disponibilidad
    r2 = check("GET /api/paciente/medicos-disponibles (post-reserva, 1 slot menos)",
               httpx.get(f"{BASE}/api/paciente/medicos-disponibles", headers=H, params=params), 200)
    mds2 = r2.json()
    if mds2:
        slots2 = len(mds2[0]["slots_disponibles"])
        diff = slots_count - slots2
        status_diff = "OK  " if diff == 1 else "FAIL"
        print(f"  [{status_diff}] Slots: {slots_count} -> {slots2} (eliminado: {diff})")
        if diff != 1:
            FAIL_LIST.append("Slot reservado no se descuenta de disponibilidad")
        else:
            PASS_LIST.append("Slot reservado no se descuenta de disponibilidad")

    r = check("GET /api/paciente/mis-citas (con 1 cita)", httpx.get(f"{BASE}/api/paciente/mis-citas", headers=H), 200)
    print(f"      {len(r.json())} cita(s) en la lista")

    # ─────────────────────────────────────────────────────────
    print()
    print("=== 7. CÓDIGO QR ===")
    if id_cita:
        r = check(f"GET /api/paciente/citas/{id_cita}/qr", httpx.get(f"{BASE}/api/paciente/citas/{id_cita}/qr", headers=H), 200)
        if r.status_code == 200:
            qr = r.json()
            print(f"      codigo_qr={qr['codigo_qr']} | fecha={qr['fecha_cita']} | hora={qr['hora_cita']} | estado={qr['estado']}")

        check("GET /api/paciente/citas/9999/qr (inexistente -> 404)",
              httpx.get(f"{BASE}/api/paciente/citas/9999/qr", headers=H), 404)

    # ─────────────────────────────────────────────────────────
    print()
    print("=== 8. CANCELAR CITA ===")
    if id_cita:
        r = check(f"DELETE /api/paciente/citas/{id_cita} (cancelar)",
                  httpx.delete(f"{BASE}/api/paciente/citas/{id_cita}", headers=H), 200)
        if r.status_code == 200:
            print(f"      {r.json()['detail']}")

        check(f"DELETE /api/paciente/citas/{id_cita} (ya cancelada -> 400)",
              httpx.delete(f"{BASE}/api/paciente/citas/{id_cita}", headers=H), 400)

        check("DELETE /api/paciente/citas/9999 (inexistente -> 404)",
              httpx.delete(f"{BASE}/api/paciente/citas/9999", headers=H), 404)

else:
    print("  [WARN] Sin médicos disponibles para hospital=3 especialidad=3 el próximo martes")

# ─────────────────────────────────────────────────────────
print()
total = len(PASS_LIST) + len(FAIL_LIST)
print("=" * 45)
print(f"RESULTADO: {len(PASS_LIST)}/{total} tests OK")
if FAIL_LIST:
    print("FALLIDOS:")
    for f in FAIL_LIST:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("TODOS LOS TESTS PASARON")
