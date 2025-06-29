from datetime import datetime, timedelta, date

TURNOS_DISPLAY = {
    "dia": "Día ☀️",
    "tarde": "Tarde 🌅",
    "noche": "Noche 🌑"
}

def get_turno_key():
    """Devuelve la clave del turno actual ('dia', 'tarde', 'noche')."""
    hour = datetime.now().hour
    if 7 <= hour < 15: return "dia"
    elif 15 <= hour < 23: return "tarde"
    else: return "noche"

def parse_periodo(periodo: str):
    """Parsea un string de periodo y devuelve cláusulas SQL, parámetros y un título."""
    where_clauses = []
    params = []
    title = ""
    today = date.today()
    periodo = periodo.lower()

    if periodo == 'hoy':
        where_clauses.append("DATE(timestamp) = ?")
        params.append(today.isoformat())
        title = "de Hoy"
    elif periodo == 'ayer':
        ayer = today - timedelta(days=1)
        where_clauses.append("DATE(timestamp) = ?")
        params.append(ayer.isoformat())
        title = f"de Ayer ({ayer.strftime('%d-%m-%Y')})"
    elif periodo == 'semana':
        where_clauses.append("strftime('%Y-%W', timestamp) = strftime('%Y-%W', 'now', 'localtime')")
        title = "de esta Semana"
    elif periodo == 'mes':
        where_clauses.append("strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now', 'localtime')")
        title = "de este Mes"
    elif ' a ' in periodo:
        try:
            start_date_str, end_date_str = [p.strip() for p in periodo.split(' a ')]
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            where_clauses.append("DATE(timestamp) BETWEEN ? AND ?")
            params.extend([start_date.isoformat(), end_date.isoformat()])
            title = f"de {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        except (ValueError, IndexError):
            return None, None, "Formato de rango de fechas incorrecto. Usa `AAAA-MM-DD a AAAA-MM-DD`."
    else:
        try:
            fecha_obj = datetime.strptime(periodo, '%Y-%m-%d').date()
            where_clauses.append("DATE(timestamp) = ?")
            params.append(fecha_obj.isoformat())
            title = f"del {fecha_obj.strftime('%d-%m-%Y')}"
        except ValueError:
            return None, None, "Periodo no válido. Usa `hoy`, `ayer`, `semana`, `mes`, una fecha `AAAA-MM-DD` o un rango."

    return where_clauses, params, title
