# =================================================================================
# ||   CÓDIGO MAESTRO v101.5 - VERSIÓN MODULAR CON COGS                          ||
# =================================================================================

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
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')

# Verificación de variables de entorno críticas
if not DISCORD_TOKEN or not GEMINI_API_KEY:
    print("--- [ERROR CRÍTICO] DISCORD_TOKEN y GEMINI_API_KEY deben estar definidos en el archivo .env ---")
    sys.exit(1)

# --- Configuración de APIs y Bot ---
genai.configure(api_key=GEMINI_API_KEY)

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, case_insensitive=True, help_command=None)

# --- Inicialización de Clientes y Modelos ---
try:
    bot.gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest', safety_settings=safety_settings)
    print("--- [CONFIG] Cliente de Gemini AI inicializado. ---")
except Exception as e:
    print(f"--- [ERROR CRÍTICO] No se pudo inicializar el modelo de Gemini: {e}. El bot no puede iniciar. ---")
    sys.exit(1)

if ELEVENLABS_API_KEY:
    bot.elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    print("--- [CONFIG] Cliente de ElevenLabs inicializado. ---")
else:
    bot.elevenlabs_client = None
    print("--- [ADVERTENCIA] No se encontró ELEVENLABS_API_KEY. Los comandos de audio estarán deshabilitados. ---")

# --- Estado Global del Bot ---
bot.elevenlabs_voices = {}
bot.dynamic_commands = {}

# --- Eventos Principales del Bot ---
@bot.event
async def on_ready():
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
    if message.author.bot or not message.content.startswith(bot.command_prefix):
        return
    
    command_name = message.content.split()[0][len(bot.command_prefix):].lower()
    if command_name in bot.dynamic_commands:
        await message.channel.send(bot.dynamic_commands[command_name])
        return
        
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
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

# --- Función Principal de Ejecución ---
async def main():
    async with bot:
        # Cargar todos los cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                    print(f'--- [COG] Cargado: {filename}')
                except Exception as e:
                    print(f"--- [ERROR COG] No se pudo cargar {filename}: {e}")
        
        print("--- [FASE 0.6] Conectando a Discord... ---")
        try:
            await bot.start(DISCORD_TOKEN)
        except discord.errors.LoginFailure:
            print("--- [ERROR CRÍTICO] El token de Discord no es válido. Revisa tu archivo .env ---")
            sys.exit(1)

app = Flask(__name__)

@app.route('/')
def home():
    return "El bot está vivo."

def run_web_server():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

if __name__ == "__main__":
    try:
        keep_alive()
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--- [INFO] Apagando el bot. ---")