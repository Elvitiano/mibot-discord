import psycopg2
import psycopg2.extras
import os
import asyncio

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    """Crea y devuelve una conexión a la base de datos PostgreSQL."""
    if not DATABASE_URL:
        raise ValueError("La variable de entorno DATABASE_URL no está definida.")
    return psycopg2.connect(DATABASE_URL)

def setup_database():
    """Configura las tablas en la base de datos PostgreSQL si no existen."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    commands = [
        "CREATE TABLE IF NOT EXISTS personas (id SERIAL PRIMARY KEY, nombre TEXT UNIQUE NOT NULL);",
        "CREATE TABLE IF NOT EXISTS datos_persona (id SERIAL PRIMARY KEY, persona_id INTEGER REFERENCES personas(id) ON DELETE CASCADE, dato_texto TEXT);",
        "CREATE TABLE IF NOT EXISTS reglas_ia (id SERIAL PRIMARY KEY, regla_texto TEXT);",
        "CREATE TABLE IF NOT EXISTS comandos_config (nombre_comando TEXT PRIMARY KEY, estado TEXT NOT NULL DEFAULT 'publico');",
        "CREATE TABLE IF NOT EXISTS permisos_comandos (user_id BIGINT, nombre_comando TEXT, PRIMARY KEY (user_id, nombre_comando));",
        "CREATE TABLE IF NOT EXISTS apodos_operador (user_id BIGINT PRIMARY KEY, apodo_dia TEXT, apodo_tarde TEXT, apodo_noche TEXT);",
        "CREATE TABLE IF NOT EXISTS operador_perfil (user_id BIGINT NOT NULL, nombre_perfil TEXT NOT NULL REFERENCES personas(nombre) ON DELETE CASCADE, PRIMARY KEY (user_id, nombre_perfil));",
        "CREATE TABLE IF NOT EXISTS lm_logs (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, perfil_usado TEXT NOT NULL, message_content TEXT NOT NULL, timestamp TIMESTAMPTZ NOT NULL, turno TEXT NOT NULL);",
        "CREATE TABLE IF NOT EXISTS exitos_logs (id SERIAL PRIMARY KEY, author_id BIGINT NOT NULL, log_message TEXT NOT NULL, timestamp TIMESTAMPTZ NOT NULL);",
        "CREATE TABLE IF NOT EXISTS chats_guardados (id SERIAL PRIMARY KEY, user_id BIGINT, user_name TEXT, message TEXT, timestamp TIMESTAMPTZ, turno TEXT);",
        "CREATE TABLE IF NOT EXISTS comandos_dinamicos (nombre_comando TEXT PRIMARY KEY, respuesta_comando TEXT, creador_id BIGINT, creador_nombre TEXT);",
        "CREATE TABLE IF NOT EXISTS tareas_programadas (id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL, author_id BIGINT NOT NULL, message_content TEXT NOT NULL, send_at TIMESTAMPTZ NOT NULL, sent INTEGER DEFAULT 0);"
    ]
    
    for command in commands:
        cur.execute(command)
        
    conn.commit()
    cur.close()
    conn.close()

async def db_execute(query, params=(), fetch=None):
    """Ejecuta una consulta en la base de datos de forma asíncrona."""
    def blocking_db_call():
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)
            
            if fetch == 'one':
                return cur.fetchone()
            if fetch == 'all':
                return cur.fetchall()
            
            conn.commit()
            return cur.rowcount
        finally:
            if conn:
                cur.close()
                conn.close()
                
    return await asyncio.to_thread(blocking_db_call)
