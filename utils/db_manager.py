import sqlite3
from datetime import datetime
import asyncio

def adapt_datetime_iso(val):
    """Adapta un objeto datetime.datetime a un string ISO 8601."""
    return val.isoformat()

def convert_datetime_iso(val):
    """Convierte un string ISO 8601 desde la DB a un objeto datetime.datetime."""
    return datetime.fromisoformat(val.decode())

sqlite3.register_adapter(datetime, adapt_datetime_iso)
sqlite3.register_converter("DATETIME", convert_datetime_iso)

def setup_database():
    with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute('''CREATE TABLE IF NOT EXISTS chats_guardados (id INTEGER PRIMARY KEY, user_id INTEGER, user_name TEXT, message TEXT, timestamp DATETIME, turno TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS comandos_dinamicos (nombre_comando TEXT PRIMARY KEY, respuesta_comando TEXT, creador_id INTEGER, creador_nombre TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS personas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS datos_persona (id INTEGER PRIMARY KEY, persona_id INTEGER, dato_texto TEXT, FOREIGN KEY (persona_id) REFERENCES personas (id) ON DELETE CASCADE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS reglas_ia (id INTEGER PRIMARY KEY, regla_texto TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS permisos_comandos (user_id INTEGER, nombre_comando TEXT, PRIMARY KEY (user_id, nombre_comando))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS comandos_config (nombre_comando TEXT PRIMARY KEY, estado TEXT NOT NULL DEFAULT 'publico')''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS tareas_programadas (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, author_id INTEGER NOT NULL, message_content TEXT NOT NULL, send_at DATETIME NOT NULL, sent INTEGER DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS operador_perfil (user_id INTEGER NOT NULL, nombre_perfil TEXT NOT NULL, FOREIGN KEY (nombre_perfil) REFERENCES personas (nombre) ON DELETE CASCADE, PRIMARY KEY (user_id, nombre_perfil))''')
        # La tabla contadores_turnos se reemplaza por un log detallado para estadísticas
        cursor.execute('''CREATE TABLE IF NOT EXISTS lm_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, perfil_usado TEXT NOT NULL, message_content TEXT NOT NULL, timestamp DATETIME NOT NULL, turno TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS apodos_operador (user_id INTEGER PRIMARY KEY, apodo_dia TEXT, apodo_tarde TEXT, apodo_noche TEXT)''')
        # Tabla para registrar interacciones exitosas (formato simple)
        cursor.execute('''CREATE TABLE IF NOT EXISTS exitos_logs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, 
                            author_id INTEGER NOT NULL,
                            log_message TEXT NOT NULL,
                            timestamp DATETIME NOT NULL
                          )''')

async def db_execute(query, params=(), fetch=None):
    def blocking_db_call():
        with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetch == 'one': return cursor.fetchone()
            if fetch == 'all': return cursor.fetchall()
            conn.commit()
            return cursor.rowcount
    return await asyncio.to_thread(blocking_db_call)
