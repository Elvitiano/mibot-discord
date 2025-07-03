from datetime import datetime, timedelta, date
import os
import pytz

TURNOS_DISPLAY = {
    "dia": "Día ☀️",
    "tarde": "Tarde 🌅",
    "noche": "Noche 🌑"
}

def get_turno_key():
    """Devuelve la clave del turno actual ('dia', 'tarde', 'noche') usando la zona horaria configurada."""
    try:
        tz_str = os.getenv('TIMEZONE', 'UTC')
        user_timezone = pytz.timezone(tz_str)
    except pytz.UnknownTimeZoneError:
        user_timezone = pytz.timezone('UTC')
        
    hour = datetime.now(user_timezone).hour
    if 7 <= hour < 15: return "dia"
    elif 15 <= hour < 23: return "tarde"
    else: return "noche"

def parse_periodo(periodo: str):
    """Parsea un string de periodo y devuelve cláusulas SQL, parámetros y un título para PostgreSQL."""
    where_clauses = []
    params = []
    title = ""
    
    tz_str = os.getenv('TIMEZONE', 'UTC')
    try:
        user_timezone = pytz.timezone(tz_str)
    except pytz.UnknownTimeZoneError:
        user_timezone = pytz.timezone('UTC')
        
    today = datetime.now(user_timezone).date()
    periodo = periodo.lower()

    date_clause = f"DATE(timestamp AT TIME ZONE '{tz_str}')"

    if periodo == 'hoy':
        where_clauses.append(f"{date_clause} = %s")
        params.append(today.isoformat())
        title = "de Hoy"
    elif periodo == 'ayer':
        ayer = today - timedelta(days=1)
        where_clauses.append(f"{date_clause} = %s")
        params.append(ayer.isoformat())
        title = f"de Ayer ({ayer.strftime('%d-%m-%Y')})"
    elif periodo == 'semana':
        where_clauses.append("to_char(timestamp AT TIME ZONE %s, 'IYYY-IW') = to_char(now() AT TIME ZONE %s, 'IYYY-IW')")
        params.extend([tz_str, tz_str])
        title = "de esta Semana"
    elif periodo == 'mes':
        where_clauses.append("to_char(timestamp AT TIME ZONE %s, 'YYYY-MM') = to_char(now() AT TIME ZONE %s, 'YYYY-MM')")
        params.extend([tz_str, tz_str])
        title = "de este Mes"
    elif ' a ' in periodo:
        try:
            start_date_str, end_date_str = [p.strip() for p in periodo.split(' a ')]
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            where_clauses.append(f"{date_clause} BETWEEN %s AND %s")
            params.extend([start_date.isoformat(), end_date.isoformat()])
            title = f"de {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        except (ValueError, IndexError):
            return None, None, "Formato de rango de fechas incorrecto. Usa `AAAA-MM-DD a AAAA-MM-DD`."
    else:
        try:
            fecha_obj = datetime.strptime(periodo, '%Y-%m-%d').date()
            where_clauses.append(f"{date_clause} = %s")
            params.append(fecha_obj.isoformat())
            title = f"del {fecha_obj.strftime('%d-%m-%Y')}"
        except ValueError:
            return None, None, "Periodo no válido. Usa `hoy`, `ayer`, `semana`, `mes`, una fecha `AAAA-MM-DD` o un rango."

    return where_clauses, params, title
