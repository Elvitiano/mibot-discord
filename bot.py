# =================================================================================
# ||   CÓDIGO MAESTRO v102.0 - VERSIÓN CON POSTGRESQL                            ||
# =================================================================================
"""
Este es el script principal que ejecuta el bot de Discord. Sus responsabilidades clave son:
- Cargar configuraciones y claves de API desde variables de entorno.
- Inicializar las conexiones con las APIs externas (Discord, Google Gemini, ElevenLabs).
- Configurar la instancia del bot de Discord, incluyendo intenciones y prefijo de comando.
- Manejar eventos globales del bot como 'on_ready', 'on_message', y 'on_command_error'.
- Cargar dinámicamente todos los módulos de comandos (Cogs) desde la carpeta /cogs.
- Implementar un sistema de comandos dinámicos que se cargan desde la base de datos.
- Ejecutar un servidor web simple (Flask) para mantener el bot activo en plataformas de hosting como Render.
- Gestionar el ciclo de vida del bot, incluyendo el inicio y el apagado seguro.
"""

print("--- [FASE 0] INICIANDO SCRIPT BOT.PY ---")
import os
import sys
import asyncio
import discord
from discord.ext import commands
import google.generativeai as genai
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from flask import Flask
from threading import Thread

from utils.db_manager import setup_database, db_execute

# --- Carga y Configuración ---
# Carga las variables de entorno desde el archivo .env para mantener las claves seguras.
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

# Verificación de variables de entorno críticas
if not all([DISCORD_TOKEN, GEMINI_API_KEY, DATABASE_URL]):
    print("--- [ERROR CRÍTICO] DISCORD_TOKEN, GEMINI_API_KEY, y DATABASE_URL deben estar definidos. ---")
    sys.exit(1)

# --- Configuración de APIs y Bot ---
# Configura la API de Gemini con la clave y ajustes de seguridad para permitir todo tipo de contenido.
genai.configure(api_key=GEMINI_API_KEY)

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# Define los 'intents' del bot, que son los permisos sobre qué eventos de Discord puede escuchar.
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Crea la instancia principal del bot, definiendo el prefijo '!' para los comandos.
bot = commands.Bot(command_prefix='!', intents=intents, case_insensitive=True, help_command=None)

# --- Inicialización de Clientes y Modelos ---
try:
    # Inicializa el modelo de IA generativa de Gemini que se usará en los cogs.
    bot.gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest', safety_settings=safety_settings)
    print("--- [CONFIG] Cliente de Gemini AI inicializado. ---")
except Exception as e:
    print(f"--- [ERROR CRÍTICO] No se pudo inicializar el modelo de Gemini: {e}. El bot no puede iniciar. ---")
    sys.exit(1)

if ELEVENLABS_API_KEY:
    # Si se proporciona una clave de ElevenLabs, inicializa el cliente para funciones de texto a voz.
    bot.elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    print("--- [CONFIG] Cliente de ElevenLabs inicializado. ---")
else:
    # Si no hay clave, se deshabilita la funcionalidad de audio.
    bot.elevenlabs_client = None
    print("--- [ADVERTENCIA] No se encontró ELEVENLABS_API_KEY. Los comandos de audio estarán deshabilitados. ---")

# --- Estado Global del Bot ---
# Diccionarios para almacenar estados que necesitan ser accesibles globalmente.
bot.elevenlabs_voices = {}
bot.dynamic_commands = {}
bot.failed_cogs = [] # Lista para rastrear cogs que no se cargaron.

# --- Eventos Principales del Bot ---
@bot.event
async def on_ready():
    """
    Se ejecuta una vez que el bot se ha conectado exitosamente a Discord.
    - Configura la base de datos.
    - Carga los comandos dinámicos desde la base de datos a la memoria.
    - Imprime un mensaje de confirmación.
    """
    await asyncio.to_thread(setup_database)
    # Cargar comandos dinámicos al iniciar
    try:
        records = await db_execute("SELECT nombre_comando, respuesta_comando FROM comandos_dinamicos", fetch='all')
        bot.dynamic_commands = {row[0]: row[1] for row in records}
        print(f"--- [FASE 1.1] {len(bot.dynamic_commands)} COMANDOS DINÁMICOS CARGADOS ---")
    except Exception as e:
        print(f"Error al cargar comandos dinámicos: {e}")
    print(f'--- [FASE 1] BOT CONECTADO Y LISTO: {bot.user} ---')

@bot.event
async def on_message(message):
    """
    Se ejecuta cada vez que se envía un mensaje en cualquier canal que el bot pueda ver.
    - Ignora los mensajes de otros bots.
    - Comprueba si el mensaje es un comando dinámico personalizado. Si lo es, envía la respuesta y termina.
    - Si no es un comando dinámico, lo pasa al procesador de comandos estándar de discord.ext.
    """
    if message.author.bot or not message.content.startswith(bot.command_prefix):
        return
    
    command_name = message.content.split()[0][len(bot.command_prefix):].lower()
    if command_name in bot.dynamic_commands:
        await message.channel.send(bot.dynamic_commands[command_name])
        return
        
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """
    Manejador de errores global para todos los comandos.
    Proporciona respuestas amigables al usuario para errores comunes como comandos no encontrados,
    cooldowns, permisos faltantes, etc., evitando que el bot se bloquee.
    """
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("🤔 Comando no reconocido.", delete_after=10)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Enfriamiento. Intenta en **{round(error.retry_after, 1)}s**.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Faltan argumentos. Revisa `!help {ctx.command.name}`.", delete_after=10)
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 No tienes permisos de Admin para este comando.", delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(f"🚫 No tienes llave o permiso para usar `!{ctx.command.name}`.", delete_after=10)
    elif isinstance(error, commands.NotOwner):
        await ctx.send("🚫 Este comando solo puede ser usado por el dueño del bot.", delete_after=10)
    else:
        print(f"[ERROR NO MANEJADO] en comando '{ctx.command.name if ctx.command else 'desconocido'}': {type(error).__name__}: {error}")
        await ctx.send("Ocurrió un error inesperado. 😔")

# --- Servidor Web para Mantener Activo en Render ---
# Esta sección crea un servidor web simple usando Flask.
# El propósito es responder a las comprobaciones de estado de plataformas como Render,
# asegurando que el servicio no se suspenda por inactividad.
app = Flask(__name__)

@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
  port = int(os.environ.get('PORT', 8080))
  print(f"--- [WEB] Iniciando servidor web en el puerto {port} ---")
  app.run(host='0.0.0.0', port=port)

def keep_alive():
    """Inicia el servidor web en un hilo separado para no bloquear el bot."""
    t = Thread(target=run_web_server)
    t.start()

# --- Función Principal de Ejecución ---
async def main():
    """
    Función principal asíncrona que prepara y ejecuta el bot.
    - Carga todas las extensiones (cogs) de la carpeta /cogs.
    - Inicia la conexión del bot a Discord usando el token.
    - Maneja errores críticos de conexión.
    """
    async with bot:
        # Cargar todos los cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                    print(f'--- [COG] Cargado: {filename}')
                except Exception as e:
                    print(f"--- [ERROR COG] No se pudo cargar {filename}: {e}")
                    bot.failed_cogs.append((filename, str(e)))
        
        print("--- [FASE 0.6] Conectando a Discord... ---")
        try:
            await bot.start(DISCORD_TOKEN)
        except discord.errors.LoginFailure:
            print("--- [ERROR CRÍTICO] El token de Discord no es válido. Revisa tu archivo .env ---")
            sys.exit(1)

if __name__ == "__main__":
    # Inicia el servidor web para mantener el bot activo.
    keep_alive()
    try:
        # Ejecuta el bucle de eventos principal del bot.
        asyncio.run(main())
    except KeyboardInterrupt:
        # Permite apagar el bot de forma limpia con Ctrl+C.
        print("\n--- [INFO] Apagando el bot. ---")