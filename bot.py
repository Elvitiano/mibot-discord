# =================================================================================
# ||   CÓDIGO MAESTRO v101.4 - VERSIÓN ESTABLE LOCAL (CON SQLITE)                 ||
# =================================================================================

# --- Importaciones necesarias ---
print("--- [FASE 0] INICIANDO SCRIPT BOT.PY ---")
import os
import discord
from discord.ext import commands, tasks
import google.generativeai as genai
from dotenv import load_dotenv
import sqlite3
from datetime import datetime, timedelta, date
import io
import asyncio
import re
from PIL import Image
from elevenlabs.client import ElevenLabs
from unidecode import unidecode
import json
from flask import Flask
from threading import Thread

# --- Adaptadores para sqlite3 y datetime para compatibilidad con Python 3.12+ ---
def adapt_datetime_iso(val):
    """Adapta un objeto datetime.datetime a un string ISO 8601."""
    return val.isoformat()

def convert_datetime_iso(val):
    """Convierte un string ISO 8601 desde la DB a un objeto datetime.datetime."""
    return datetime.fromisoformat(val.decode())

sqlite3.register_adapter(datetime, adapt_datetime_iso)
sqlite3.register_converter("DATETIME", convert_datetime_iso)

# --- Carga y Configuración ---
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')

# Configuración de los clientes de API
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

if ELEVENLABS_API_KEY:
    elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    print("--- [CONFIG] Cliente de ElevenLabs inicializado. ---")
else:
    elevenlabs_client = None
    print("--- [ADVERTENCIA] No se encontró ELEVENLABS_API_KEY. Los comandos de audio estarán deshabilitados. ---")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

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

# --- Sistema de Ayuda Interactivo ---

class HelpView(discord.ui.View):
    def __init__(self, context, mapping):
        super().__init__(timeout=120.0)
        self.context = context
        self.mapping = mapping
        self.message = None
        
        visible_categories = self._get_visible_categories()
        self.add_item(CategorySelect(visible_categories))

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    def _get_visible_categories(self):
        with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT nombre_comando, estado FROM comandos_config")
            configs = {row[0]: row[1] for row in cursor.fetchall()}
            cursor.execute("SELECT nombre_comando FROM permisos_comandos WHERE user_id = ?", (self.context.author.id,))
            perms = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT nombre_comando FROM comandos_dinamicos ORDER BY nombre_comando ASC")
            custom_cmds = cursor.fetchall()

        es_admin = self.context.author.guild_permissions.administrator
        
        all_categories = {
            "Gestión de Operadores": ['apodo', 'verapodo', 'quitarapodo', 'listaapodos', 'asignar', 'desasignar', 'misperfiles', 'lm', 'sincronizar-perfiles', 'desincronizar-perfiles'],
            "Estadísticas y Registros": ['estadisticas', 'registrolm'],
            "Gestión de Perfiles (IA)": ['crearperfil', 'borrarperfil', 'listaperfiles', 'agghistorial', 'verinfo'],
            "Análisis con IA": ['reply', 'consejo', 'preguntar'],
            "Audio (ElevenLabs)": ['sync_elevenlabs', 'audio', 'audiolab'],
            "Memoria del Bot": ['guardar', 'buscar', 'resumir'],
            "Tareas Programadas": ['programar', 'programar-ia', 'programar-serie', 'tareas', 'borrartarea'],
            "Administración General": ['backup', 'privatizar', 'publicar', 'permitir', 'denegar', 'estado_comandos', 'anuncio', 'aggregla', 'listareglas', 'borrarregla', 'exportar-config', 'importar-config'],
            "Comandos Personalizados": [cmd[0] for cmd in custom_cmds]
        }

        visible_categories = {}
        for cat_name, cmd_list in all_categories.items():
            visible_cmds = []
            if not cmd_list: continue

            for cmd_name in cmd_list:
                command = self.context.bot.get_command(cmd_name)
                if command and not command.hidden:
                    estado_cmd = configs.get(command.name, 'publico')
                    if es_admin or estado_cmd == 'publico' or command.name in perms:
                        visible_cmds.append(command)
                elif cat_name == "Comandos Personalizados":
                    visible_cmds.append(cmd_name)

            if visible_cmds:
                visible_categories[cat_name] = visible_cmds
        
        return visible_categories

class CategorySelect(discord.ui.Select):
    def __init__(self, categories):
        self.categories = categories
        options = [discord.SelectOption(label=cat_name, description=f"Ver comandos de {cat_name}") for cat_name in categories.keys()]
        super().__init__(placeholder="Elige una categoría para ver sus comandos...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.view.context.author:
            await interaction.response.send_message("No puedes usar este menú de ayuda.", ephemeral=True)
            return

        selected_category = self.values[0]
        commands_in_category = self.categories[selected_category]

        embed = discord.Embed(title=f"Comandos en: {selected_category}", color=discord.Color.blue())
        embed.set_footer(text="Usa !help <comando> para más detalles sobre un comando específico.")
        
        description = ""
        if selected_category == "Comandos Personalizados":
            description = ", ".join([f"`{cmd_name}`" for cmd_name in commands_in_category])
        else:
            for command in commands_in_category:
                description += f"**`{self.view.context.prefix}{command.name}`**: {command.help or 'Sin descripción.'}\n"
        
        embed.description = description if description else "No hay comandos disponibles en esta categoría."
        
        await interaction.response.edit_message(embed=embed)

class MyHelpCommand(commands.HelpCommand):
    def get_command_signature(self, command):
        return f'{self.context.prefix}{command.name} {command.signature}'

    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="🤖 Menú de Ayuda de MiBotGemini 🤖", color=discord.Color.dark_purple())
        embed.description = "Selecciona una categoría del menú desplegable para ver sus comandos.\nUsa `!help <comando>` para obtener información detallada sobre un comando específico."
        view = HelpView(self.context, mapping)
        view.message = await self.get_destination().send(embed=embed, view=view)

    async def send_command_help(self, command):
        if command.hidden:
            return
        
        embed = discord.Embed(title=f"Ayuda para: `!{command.name}`", color=discord.Color.dark_green())
        
        alias = ", ".join([f"`{a}`" for a in command.aliases])
        if alias:
            embed.add_field(name="Alias", value=alias, inline=False)

        usage = f"`{self.get_command_signature(command)}`"
        embed.add_field(name="Uso", value=usage, inline=False)

        if command.help:
            embed.add_field(name="Descripción", value=command.help, inline=False)

        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error):
        embed = discord.Embed(title="Error de Ayuda", description=error, color=discord.Color.red())
        await self.get_destination().send(embed=embed)

    async def command_not_found(self, string):
        with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT respuesta_comando, creador_nombre FROM comandos_dinamicos WHERE nombre_comando = ?", (string,))
            result = cursor.fetchone()
        
        if result:
            respuesta, creador = result
            embed = discord.Embed(title=f"Ayuda para Comando Personalizado: `!{string}`", color=discord.Color.dark_blue())
            embed.add_field(name="Respuesta", value=f"```{respuesta}```", inline=False)
            embed.add_field(name="Creador", value=creador, inline=False)
            await self.get_destination().send(embed=embed)
        else:
            await self.send_error_message(f'No se encontró ningún comando llamado "{string}".')

bot = commands.Bot(command_prefix='!', intents=intents, case_insensitive=True, help_command=MyHelpCommand())
bot.elevenlabs_voices = {}

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
        # --- Tablas actualizadas para el formato LM por turnos ---
        cursor.execute('''CREATE TABLE IF NOT EXISTS operador_perfil (user_id INTEGER NOT NULL, nombre_perfil TEXT NOT NULL, FOREIGN KEY (nombre_perfil) REFERENCES personas (nombre) ON DELETE CASCADE, PRIMARY KEY (user_id, nombre_perfil))''')
        # La tabla contadores_turnos se reemplaza por un log detallado para estadísticas
        cursor.execute('''CREATE TABLE IF NOT EXISTS lm_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, perfil_usado TEXT NOT NULL, message_content TEXT NOT NULL, timestamp DATETIME NOT NULL, turno TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS apodos_operador (user_id INTEGER PRIMARY KEY, apodo_dia TEXT, apodo_tarde TEXT, apodo_noche TEXT)''')

@bot.event
async def on_ready():
    setup_database()
    check_scheduled_tasks.start()
    bot.dynamic_commands = {}
    try:
        with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT nombre_comando, respuesta_comando FROM comandos_dinamicos")
            bot.dynamic_commands = {row[0]: row[1] for row in cursor.fetchall()}
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
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Enfriamiento. Intenta en **{round(error.retry_after, 1)}s**.", delete_after=10)
        return
        
    if isinstance(error, commands.MissingRequiredArgument):
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

# --- Comandos de Administración y Permisos ---
@bot.command(name='backup', help='Crea una copia de seguridad de la base de datos.')
@commands.is_owner()
async def backup(ctx):
    try:
        await ctx.send(file=discord.File('memoria_bot.db', f'backup_{datetime.now().strftime("%Y-%m-%d_%H-%M")}.db'))
    except Exception as e:
        await ctx.send("❌ Error al crear backup."); print(f"Error en !backup: {e}")

@bot.command(name='privatizar', help='Hace que un comando sea de uso restringido.')
@commands.has_permissions(administrator=True)
async def privatizar(ctx, nombre_comando: str):
    cmd = bot.get_command(nombre_comando.lower())
    if not cmd or cmd.name in ['privatizar', 'publicar', 'permitir', 'denegar', 'estado_comandos', 'backup']:
        await ctx.send(f"❌ No se puede privatizar `!{nombre_comando}`."); return
    await db_execute("INSERT OR REPLACE INTO comandos_config (nombre_comando, estado) VALUES (?, ?)", (cmd.name, 'privado'))
    await ctx.send(f"🔒 El comando `!{cmd.name}` ahora es privado.")

@bot.command(name='publicar', help='Hace que un comando sea de uso público.')
@commands.has_permissions(administrator=True)
async def publicar(ctx, nombre_comando: str):
    cmd = bot.get_command(nombre_comando.lower())
    if not cmd: await ctx.send(f"❌ No existe el comando `!{nombre_comando}`."); return
    await db_execute("INSERT OR REPLACE INTO comandos_config (nombre_comando, estado) VALUES (?, ?)", (cmd.name, 'publico'))
    await ctx.send(f"🌍 El comando `!{cmd.name}` ahora es público.")

@bot.command(name='permitir', help='Concede a un usuario permiso para usar un comando privado.')
@commands.has_permissions(administrator=True)
async def permitir(ctx, miembro: discord.Member, nombre_comando: str):
    cmd_name = nombre_comando.lower()
    if not bot.get_command(cmd_name): await ctx.send(f"❌ No existe el comando `!{cmd_name}`."); return
    await db_execute("INSERT OR REPLACE INTO permisos_comandos (user_id, nombre_comando) VALUES (?, ?)", (miembro.id, cmd_name))
    await ctx.send(f"🔑 ¡Llave entregada! {miembro.mention} ahora puede usar `!{cmd_name}`.")

@bot.command(name='denegar', help='Quita el permiso a un usuario para un comando.')
@commands.has_permissions(administrator=True)
async def denegar(ctx, miembro: discord.Member, nombre_comando: str):
    rows = await db_execute("DELETE FROM permisos_comandos WHERE user_id = ? AND nombre_comando = ?", (miembro.id, nombre_comando.lower()))
    if rows == 0: await ctx.send(f"🤔 {miembro.mention} no tenía permiso para `!{nombre_comando}`.")
    else: await ctx.send(f"✅ Acceso a `!{nombre_comando}` revocado para {miembro.mention}.")

@bot.command(name='estado_comandos', help='Muestra el estado de los comandos.')
@commands.has_permissions(administrator=True)
async def estado_comandos(ctx):
    configs = await db_execute("SELECT nombre_comando, estado FROM comandos_config", fetch='all')
    configuraciones = {row[0]: row[1] for row in configs}
    embed = discord.Embed(title="Estado de Permisos de Comandos", color=discord.Color.dark_grey())
    description = ""
    for cmd in sorted(bot.commands, key=lambda c: c.name):
        if cmd.hidden: continue
        estado_texto = configuraciones.get(cmd.name, 'publico')
        estado_emoji = 'Privado 🔒' if estado_texto == 'privado' else 'Público 🌍'
        description += f"**`!{cmd.name}`**: {estado_emoji}\n"
    embed.description = description
    await ctx.send(embed=embed)

# --- Comandos de Gestión de Perfiles y Reglas ---
@bot.command(name='crearperfil', help='Crea uno o más perfiles. Uso: !crearperfil <nombre1> [nombre2] ...')
@commands.has_permissions(administrator=True)
async def crear_perfil(ctx, *, nombres: str):
    if not nombres:
        await ctx.send("❌ Debes especificar al menos un nombre de perfil."); return

    nombres_lista = [n.lower() for n in nombres.split()]
    creados = []
    existentes = []

    for nombre in nombres_lista:
        try:
            await db_execute("INSERT INTO personas (nombre) VALUES (?)", (nombre,))
            creados.append(nombre)
        except sqlite3.IntegrityError:
            existentes.append(nombre)

    respuesta = ""
    if creados:
        respuesta += f"✅ Perfiles creados: `{', '.join(creados)}`\n"
    if existentes:
        respuesta += f"🤔 Perfiles que ya existían: `{', '.join(existentes)}`"
    
    await ctx.send(respuesta.strip())

@bot.command(name='agghistorial', help='Añade un dato al historial de un perfil.')
@commands.has_permissions(administrator=True)
async def agghistorial(ctx, nombre_perfil: str, *, dato: str):
    persona = await db_execute("SELECT id FROM personas WHERE nombre = ?", (nombre_perfil.lower(),), fetch='one')
    if persona:
        await db_execute("INSERT INTO datos_persona (persona_id, dato_texto) VALUES (?, ?)", (persona[0], dato))
        await ctx.send(f"✅ Dato añadido al perfil `{nombre_perfil.lower()}`.")
    else:
        await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`.")

@bot.command(name='verinfo', help='Muestra la información de un perfil.')
async def ver_info(ctx, nombre_perfil: str):
    persona = await db_execute("SELECT id FROM personas WHERE nombre = ?", (nombre_perfil.lower(),), fetch='one')
    if not persona: await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`."); return
    
    datos = await db_execute("SELECT dato_texto FROM datos_persona WHERE persona_id = ?",(persona[0],), fetch='all')
    if not datos: await ctx.send(f"El perfil `{nombre_perfil.lower()}` no tiene historial."); return
        
    embed = discord.Embed(title=f"Historial del Perfil: {nombre_perfil.lower()}", color=discord.Color.orange())
    embed.description = "\n".join([f"- {dato[0]}" for dato in datos])
    await ctx.send(embed=embed)

@bot.command(name='borrarperfil', help='Borra un perfil y todo su historial.')
@commands.has_permissions(administrator=True)
async def borrar_perfil(ctx, nombre_perfil: str):
    rows = await db_execute("DELETE FROM personas WHERE nombre = ?", (nombre_perfil.lower(),))
    if rows > 0:
        await ctx.send(f"✅ Perfil `{nombre_perfil.lower()}` y su historial eliminados.")
    else:
        await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`.")
        
@bot.command(name='listaperfiles', aliases=['verperfiles'], help='Muestra todos los perfiles y a quién están asignados.')
@commands.has_permissions(administrator=True)
async def listaperfiles(ctx):
    perfiles = await db_execute("SELECT nombre FROM personas ORDER BY nombre ASC", fetch='all')
    if not perfiles:
        await ctx.send("No hay perfiles creados en la base de datos."); return

    asignaciones = await db_execute("SELECT nombre_perfil, user_id FROM operador_perfil", fetch='all')
    mapa_asignaciones = {}
    for nombre_perfil, user_id in asignaciones:
        if nombre_perfil not in mapa_asignaciones:
            mapa_asignaciones[nombre_perfil] = []
        mapa_asignaciones[nombre_perfil].append(user_id)

    embed = discord.Embed(title="📊 Estado de Asignación de Perfiles", color=discord.Color.blue())
    description = ""
    for perfil_tuple in perfiles:
        nombre_perfil = perfil_tuple[0]
        description += f"### Perfil: `{nombre_perfil}`\n"
        
        usuarios_asignados = mapa_asignaciones.get(nombre_perfil, [])
        if not usuarios_asignados:
            description += "👤 *No asignado a ningún operador.*\n\n"
        else:
            menciones = []
            for user_id in usuarios_asignados:
                miembro = ctx.guild.get_member(user_id)
                menciones.append(miembro.mention if miembro else f"ID: {user_id}")
            description += f"👤 **Asignado a:** {', '.join(menciones)}\n\n"

    if len(description) > 4000:
        description = description[:4000] + "\n\n*[Resultados truncados]*"

    embed.description = description
    await ctx.send(embed=embed)

@bot.command(name='aggregla', help='Añade una regla para la IA.')
@commands.has_permissions(administrator=True)
async def aggregla(ctx, *, regla: str):
    await db_execute("INSERT INTO reglas_ia (regla_texto) VALUES (?)", (regla,))
    await ctx.send("✅ Nueva regla añadida a la IA.")

@bot.command(name='listareglas', help='Muestra las reglas de la IA.')
async def listareglas(ctx):
    reglas = await db_execute("SELECT id, regla_texto FROM reglas_ia ORDER BY id ASC", fetch='all')
    if not reglas: await ctx.send("No hay reglas personalizadas para la IA."); return
    embed = discord.Embed(title="Libro de Reglas de la IA", color=discord.Color.light_grey())
    embed.description = "\n".join(f"**{r_id}**: {r_text}" for r_id, r_text in reglas)
    await ctx.send(embed=embed)

@bot.command(name='borrarregla', help='Borra una regla de la IA por su número.')
@commands.has_permissions(administrator=True)
async def borrarregla(ctx, regla_id: int):
    rows = await db_execute("DELETE FROM reglas_ia WHERE id = ?", (regla_id,))
    if rows == 0: await ctx.send(f"🤔 No encontré una regla con el ID `{regla_id}`.")
    else: await ctx.send(f"✅ Regla `{regla_id}` borrada.")

# --- Comandos de IA y Audio ---
def process_image_and_db_for_reply(nombre_perfil, attachment_bytes):
    hoja_personaje = ""
    with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT regla_texto FROM reglas_ia ORDER BY id ASC")
        reglas_ia = cursor.fetchall()
        if nombre_perfil:
            cursor.execute("SELECT id FROM personas WHERE nombre = ?", (nombre_perfil.lower(),))
            persona_result = cursor.fetchone()
            if not persona_result: raise ValueError(f"No encontré el perfil `{nombre_perfil.lower()}`.")
            cursor.execute("SELECT dato_texto FROM datos_persona WHERE persona_id = ?", (persona_result[0],))
            hoja_personaje = f"**TU PERSONAJE:**\nTú eres '{nombre_perfil}'.\n" + "\n".join(f"- {dato[0]}" for dato in cursor.fetchall())
    
    with Image.open(io.BytesIO(attachment_bytes)) as img:
        rgb_img = img.convert('RGB')
        rgb_img.thumbnail((1024, 1024))
        buffer = io.BytesIO()
        rgb_img.save(buffer, format="JPEG")
        return hoja_personaje, reglas_ia, buffer.getvalue()

@bot.command(name='reply', help='Usa un perfil para analizar una foto/bio.')
@commands.cooldown(1, 120, commands.BucketType.user) 
async def reply(ctx, nombre_perfil: str = None):
    if not ctx.message.attachments:
        await ctx.send("❌ Debes adjuntar una imagen.", delete_after=10); reply.reset_cooldown(ctx); return
    attachment = ctx.message.attachments[0]
    if not attachment.content_type.startswith('image/'):
        await ctx.send("❌ El archivo no es una imagen.", delete_after=10); reply.reset_cooldown(ctx); return
    
    async with ctx.typing():
        try:
            image_bytes = await attachment.read()
            hoja_personaje, reglas_ia, image_bytes_procesados = await asyncio.to_thread(
                process_image_and_db_for_reply, nombre_perfil, image_bytes)
            
            image_for_gemini = {'mime_type': 'image/jpeg', 'data': image_bytes_procesados}
            prompt_dinamico = """**ROL Y OBJETIVO:** Eres un 'coach' de citas carismático y natural. Tu objetivo es crear DOS planes de conversación (openers) para un sitio de citas.
**REGLAS CRÍTICAS (NO IGNORAR):**
- **NUNCA SALUDES:** Jamás inicies una línea con "Hola", "Hey", o cualquier otro saludo. Ve directo al grano.
- **EVIDENCIA CONCRETA:** Basa el 100% de tus observaciones en detalles VISUALES de la foto o frases EXACTAS de su biografía.
- **SÉ REAL Y DIRECTO:** Tu tono es el de un amigo. Incorpora humor natural ('Jajaja').
- **ESTRUCTURA EXACTA:** DOS opciones. Cada una con EXACTAMENTE 5 puntos. Separa las opciones con `---`.
- **RESTRICCIONES ADICIONALES:** NO uses comillas (`""`). NO uses paréntesis como (Opinión)."""
            if hoja_personaje: prompt_dinamico += f"\n{hoja_personaje}"
            if reglas_ia: prompt_dinamico += "\n**REGLAS ADICIONALES OBLIGATORIAS:**\n" + "\n".join(f"- {regla[0]}" for regla in reglas_ia)
            
            response = await gemini_model.generate_content_async([prompt_dinamico, image_for_gemini])
            titulo = f"**Estrategias para `{nombre_perfil.lower()}`:**" if nombre_perfil else "**Estrategias de conversación:**"
            partes = response.text.split('---')
            respuesta_final = f"{titulo}\n\n**Opción 1:**\n{partes[0].strip()}"
            if len(partes) > 1: respuesta_final += f"\n\n**Opción 2:**\n{partes[1].strip()}"
            await ctx.send(respuesta_final)
        except ValueError as ve: await ctx.send(f"❌ {ve}")
        except Exception as e: print(f"Error en !reply: {e}"); await ctx.send("❌ Error al generar la respuesta.")

@bot.command(name='consejo', help='Analiza una imagen y da hasta 5 detalles relevantes.')
@commands.cooldown(1, 60, commands.BucketType.user)
async def consejo(ctx):
    if not ctx.message.attachments:
        await ctx.send("❌ Debes adjuntar una imagen.", delete_after=10); consejo.reset_cooldown(ctx); return
    attachment = ctx.message.attachments[0]
    if not attachment.content_type.startswith('image/'):
        await ctx.send("❌ El archivo no es una imagen.", delete_after=10); consejo.reset_cooldown(ctx); return
    async with ctx.typing():
        try:
            image_bytes = await attachment.read()
            
            # Procesar la imagen para optimizarla y estandarizarla
            with Image.open(io.BytesIO(image_bytes)) as img:
                rgb_img = img.convert('RGB')
                rgb_img.thumbnail((1024, 1024)) # Reducir tamaño si es muy grande
                buffer = io.BytesIO()
                rgb_img.save(buffer, format="JPEG")
                image_bytes_procesados = buffer.getvalue()

            image_for_gemini = {'mime_type': 'image/jpeg', 'data': image_bytes_procesados}
            prompt_consejo = """**ROL Y OBJETIVO:** Actúa como un 'coach' de citas y un agudo observador. Tu misión es identificar de 3 a 4 detalles visuales CONCRETOS en la imagen adjunta y, para cada uno, proporcionar frases listas para usar en una conversación.
**FORMATO DE SALIDA (MUY IMPORTANTE):** Tu respuesta debe seguir esta estructura exacta. NO uses las palabras "Detalle" u "Opción". Sé directo.
**Sobre [Nombre del Detalle 1]:**
- "[Frase 1]"
- "[Frase 2]" """
            response = await gemini_model.generate_content_async([prompt_consejo, image_for_gemini])
            await ctx.send(f"**Puntos de partida basados en la imagen:**\n\n{response.text}")
        except Exception as e:
            print(f"Error en !consejo: {e}"); await ctx.send("❌ Error al analizar la imagen.")

# --- Comandos de Memoria ---
@bot.command(name='guardar', help='Guarda un mensaje en la memoria.')
async def guardar_chat(ctx, *, mensaje: str):
    now = datetime.now()
    turno_key = get_turno_key()
    turno_display = TURNOS_DISPLAY.get(turno_key, "Desconocido")
    await db_execute("INSERT INTO chats_guardados (user_id, user_name, message, timestamp, turno) VALUES (?, ?, ?, ?, ?)", (ctx.author.id, ctx.author.name, mensaje, now, turno_display))
    await ctx.send(f"✅ ¡Mensaje guardado! (Turno: {turno_display})")

@bot.command(name='buscar', help='Busca en la memoria. Uso: !buscar <término/fecha>')
async def buscar(ctx, *, query: str):
    sql_query = ""
    params = ()
    title = ""
    
    try:
        search_date = datetime.strptime(query, '%Y-%m-%d').date()
        sql_query = "SELECT * FROM chats_guardados WHERE DATE(timestamp) = ? ORDER BY timestamp ASC"
        params = (search_date,)
        title = f"Memoria del {search_date.strftime('%d-%m-%Y')}"
    except ValueError:
        # Usar .strip() para evitar que búsquedas como "que paso hoy" se confundan con "hoy"
        clean_query = query.lower().strip()
        if clean_query == 'hoy':
            search_date = date.today()
            sql_query = "SELECT * FROM chats_guardados WHERE DATE(timestamp) = ? ORDER BY timestamp ASC"
            params = (search_date,)
            title = f"Memoria de hoy ({search_date.strftime('%d-%m-%Y')})"
        elif clean_query == 'ayer':
            search_date = date.today() - timedelta(days=1)
            sql_query = "SELECT * FROM chats_guardados WHERE DATE(timestamp) = ? ORDER BY timestamp ASC"
            params = (search_date,)
            title = f"Memoria de ayer ({search_date.strftime('%d-%m-%Y')})"
        else:
            sql_query = "SELECT * FROM chats_guardados WHERE LOWER(message) LIKE ? ORDER BY timestamp DESC"
            params = (f"%{query.lower()}%",)
            title = f"Resultados para: '{query}'"
    
    rows = await db_execute(sql_query, params, fetch='all')
    if not rows: 
        await ctx.send(f"🤔 No encontré resultados para: **{query}**.")
        return
    
    description = ""
    for r in rows:
        description += f"**- {datetime.fromisoformat(r[4]).strftime('%H:%M')} por {r[2]}**: `{r[3]}`\n"
        
    embed = discord.Embed(title=title, color=discord.Color.green())
    if len(description) > 4000:
        description = description[:4000] + "\n\n*[Resultados truncados por su longitud]*"
    
    embed.description = description
    await ctx.send(embed=embed)

@bot.command(name='resumir', help='Crea un resumen con IA de la memoria. Uso: !resumir <hoy/ayer/término>')
async def resumir(ctx, *, query: str):
    # 1. Reutilizar la lógica de búsqueda de !buscar para obtener los mensajes
    sql_query = ""
    params = ()
    title_prefix = ""
    
    try:
        search_date = datetime.strptime(query, '%Y-%m-%d').date()
        sql_query = "SELECT user_name, message FROM chats_guardados WHERE DATE(timestamp) = ? ORDER BY timestamp ASC"
        params = (search_date,)
        title_prefix = f"Resumen del {search_date.strftime('%d-%m-%Y')}"
    except ValueError:
        clean_query = query.lower().strip()
        if clean_query == 'hoy':
            search_date = date.today()
            sql_query = "SELECT user_name, message FROM chats_guardados WHERE DATE(timestamp) = ? ORDER BY timestamp ASC"
            params = (search_date,)
            title_prefix = f"Resumen de hoy ({search_date.strftime('%d-%m-%Y')})"
        elif clean_query == 'ayer':
            search_date = date.today() - timedelta(days=1)
            sql_query = "SELECT user_name, message FROM chats_guardados WHERE DATE(timestamp) = ? ORDER BY timestamp ASC"
            params = (search_date,)
            title_prefix = f"Resumen de ayer ({search_date.strftime('%d-%m-%Y')})"
        else:
            sql_query = "SELECT user_name, message FROM chats_guardados WHERE LOWER(message) LIKE ? ORDER BY timestamp DESC"
            params = (f"%{query.lower()}%",)
            title_prefix = f"Resumen sobre '{query}'"

    async with ctx.typing():
        rows = await db_execute(sql_query, params, fetch='all')
        if not rows: 
            await ctx.send(f"🤔 No encontré nada que resumir para: **{query}**.")
            return
        
        # 2. Formatear los mensajes para la IA
        chat_log = "\n".join([f"{row[0]}: {row[1]}" for row in rows])
        
        # Limitar la longitud para no exceder el límite de la API
        if len(chat_log) > 15000:
            chat_log = chat_log[:15000]

        # 3. Enviar a Gemini para el resumen
        try:
            prompt_resumen = f"""**TAREA:** Eres un asistente que resume conversaciones. Analiza el siguiente registro de chat y extrae los puntos, ideas o eventos más importantes. Presenta el resumen en una lista de viñetas (bullet points). Sé conciso y claro.

**REGISTRO DE CHAT:**
---
{chat_log}
---

**RESUMEN:**"""
            
            response = await gemini_model.generate_content_async(prompt_resumen)
            
            embed = discord.Embed(title=f"🧠 {title_prefix}", color=discord.Color.blue())
            embed.description = response.text
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send("❌ Error al generar el resumen con la IA.")
            print(f"Error en !resumir: {e}")

# --- MÓDULO DE GENERACIÓN DE AUDIO ---
@bot.command(name='sync_elevenlabs', help='(Admin) Sincroniza las voces de ElevenLabs.')
@commands.has_permissions(administrator=True)
async def sync_elevenlabs(ctx):
    if not elevenlabs_client: await ctx.send("❌ Cliente de ElevenLabs no configurado."); return
    async with ctx.typing():
        try:
            voices = await asyncio.to_thread(elevenlabs_client.voices.get_all)
            bot.elevenlabs_voices.clear()
            my_voices = [v for v in voices.voices if v.category != 'premade']
            emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"] + [chr(0x1f1e6 + i) for i in range(26)]
            description = "Tus voces personalizadas han sido sincronizadas:\n\n"
            for i, voice in enumerate(my_voices):
                if i < len(emojis):
                    bot.elevenlabs_voices[emojis[i]] = {'id': voice.voice_id, 'name': voice.name}
                    description += f"{emojis[i]} **{voice.name}**\n"
            if not bot.elevenlabs_voices: await ctx.send("🤔 No se encontraron voces personalizadas en tu cuenta."); return
            embed = discord.Embed(title="🎙️ Librería de Voces Personalizadas Actualizada 🎙️", description=description, color=discord.Color.brand_green())
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("❌ Error al sincronizar voces."); print(f"Error en !sync_elevenlabs: {e}")

async def get_refined_script(ctx, original_text):
    base_prompt = f"""**Primary Task:** You are a dialogue processing AI. Your input is a text. Your output must be two processed versions of that text, separated by '---'.
**CRITICAL RULE 1: Language Preservation**
- Identify the language of the "ORIGINAL TEXT" below.
- Your entire response MUST be in that exact same language.
- DO NOT TRANSLATE the text. The output language must match the input language.
**CRITICAL RULE 2: Content Refinement**
- If you see instructions in parentheses like (sarcastic) or (sadly), rewrite the sentence to reflect that tone and remove the parenthetical instruction.
- The final text should be between 40 and 60 words. If the original text is too short, expand it creatively while staying on topic.
**CRITICAL RULE 3: Output Formatting**
1.  **Version 1 (With Tags):** The first version should include speech tags like `[pause]`, `[laughs]`, or `[sighs]` to make it sound natural.
2.  **Separator:** Use '---' to separate the two versions.
3.  **Version 2 (Clean):** The second version should be identical to the first, but with all speech tags (like `[pause]`) completely removed.
4.  **DO NOT** include any titles, headers, or markdown like `**`."""
    
    is_first_run = True
    msg_to_edit = None
    while True:
        async with ctx.typing():
            if is_first_run:
                prompt = f'{base_prompt}\n**ORIGINAL TEXT:** "{original_text}"'
                is_first_run = False
            else:
                prompt = f'{base_prompt}\n**IMPORTANT INSTRUCTION:** Please generate a new, different and creative alternative to the previous suggestion.\n**ORIGINAL TEXT:** "{original_text}"'

            response = await gemini_model.generate_content_async(prompt)
            parts = response.text.split('---')
            script_with_tags = re.sub(r'\*\*', '', parts[0]).strip()
            clean_script = re.sub(r'\[.*?\]', '', script_with_tags).strip()

            embed = discord.Embed(title="🎬 Guion Propuesto 🎬", color=discord.Color.blurple())
            embed.add_field(name="1️⃣ Versión con Etiquetas (Experimental)", value=f"```\n{script_with_tags}\n```", inline=False)
            embed.add_field(name="2️⃣ Versión Limpia (Recomendada)", value=f"```\n{clean_script}\n```", inline=False)
            embed.set_footer(text="Reacciona con 🔄 para regenerar, o elige la versión para el audio.")
            
            if is_first_run:
                msg_to_edit = await ctx.send(embed=embed)
            else:
                await msg_to_edit.edit(embed=embed)

            await msg_to_edit.add_reaction("🔄"); await msg_to_edit.add_reaction("1️⃣"); await msg_to_edit.add_reaction("2️⃣")

            def check(r, u): return u == ctx.author and str(r.emoji) in ["🔄", "1️⃣", "2️⃣"] and r.message.id == msg_to_edit.id
            try:
                reaction, _ = await bot.wait_for('reaction_add', timeout=180.0, check=check)
                
                if str(reaction.emoji) == "🔄":
                    await msg_to_edit.clear_reactions() # Limpiar para nueva iteración
                    continue

                chosen_script = None
                if str(reaction.emoji) == "1️⃣":
                    chosen_script = script_with_tags
                elif str(reaction.emoji) == "2️⃣":
                    chosen_script = clean_script
                
                if chosen_script:
                    final_embed = discord.Embed(
                        title="📝 Guion Final Seleccionado",
                        description=f"```\n{chosen_script}\n```",
                        color=discord.Color.green()
                    )
                    final_embed.set_footer(text="Puedes copiar este texto.")
                    await msg_to_edit.edit(embed=final_embed)
                    await msg_to_edit.clear_reactions()
                    return chosen_script

            except asyncio.TimeoutError:
                await msg_to_edit.delete()
                await ctx.send("Tiempo de espera agotado.", delete_after=10)
                return None

@bot.command(name='audio', help='Corrige y refina un texto para un guion.')
async def audio(ctx, *, texto: str):
    async with ctx.typing():
        await get_refined_script(ctx, texto)

@bot.command(name='audiolab', help='(Privado) Genera un audio completo desde un texto.')
@commands.has_permissions(administrator=True)
async def audiolab(ctx, *, texto: str):
    if not elevenlabs_client: await ctx.send("❌ Cliente de ElevenLabs no configurado."); return
    if not bot.elevenlabs_voices: await ctx.send("❌ No hay voces sincronizadas. Usa `!sync_elevenlabs`."); return

    final_script = await get_refined_script(ctx, texto)
    if not final_script: return

    description = "Guion aceptado. Selecciona una voz:\n\n" + "\n".join(f"{e} **{v['name']}**" for e, v in bot.elevenlabs_voices.items())
    embed = discord.Embed(title="🎤 Selección de Voz 🎤", description=description, color=discord.Color.teal())
    voice_msg = await ctx.send(embed=embed)
    for emoji in bot.elevenlabs_voices.keys(): await voice_msg.add_reaction(emoji)
    
    def check_voice(r, u): return u == ctx.author and str(r.emoji) in bot.elevenlabs_voices and r.message.id == voice_msg.id
    try:
        reaction, _ = await bot.wait_for('reaction_add', timeout=120.0, check=check_voice)
        voice_id = bot.elevenlabs_voices[str(reaction.emoji)]['id']
        voice_name = bot.elevenlabs_voices[str(reaction.emoji)]['name']
        await voice_msg.delete()

        while True:
            generating_msg = await ctx.send(f"🎙️ Generando audio con la voz de **{voice_name}**...")
            audio_bytes = None
            try:
                def generate_audio_bytes():
                    audio_stream = elevenlabs_client.text_to_speech.convert(voice_id=voice_id, text=final_script)
                    return b"".join(chunk for chunk in audio_stream)
                audio_bytes = await asyncio.to_thread(generate_audio_bytes)
            except Exception as e:
                await generating_msg.delete()
                print(f"Error generando audio en ElevenLabs: {e}")
                await ctx.send("❌ Hubo un error al generar el audio con ElevenLabs.")
                return

            await generating_msg.delete()
            audio_message = await ctx.send(content=f"**Texto utilizado:**\n```\n{final_script}\n```", file=discord.File(io.BytesIO(audio_bytes), filename="audio.mp3"))

            await audio_message.add_reaction("🔁"); await audio_message.add_reaction("✅")
            def check_audio_regen(r, u): return u == ctx.author and str(r.emoji) in ["🔁", "✅"] and r.message.id == audio_message.id
            try:
                regen_reaction, _ = await bot.wait_for('reaction_add', timeout=180.0, check=check_audio_regen)
                if str(regen_reaction.emoji) == "✅":
                    await audio_message.edit(content=f"**Audio Final Aceptado.**\n\n**Texto utilizado:**\n```\n{final_script}\n```")
                    await audio_message.clear_reactions()
                    break 
                elif str(regen_reaction.emoji) == "🔁":
                    await audio_message.delete()
            except asyncio.TimeoutError:
                await audio_message.edit(content=f"**Texto utilizado:**\n```\n{final_script}\n```\n*Sesión de regeneración finalizada.*")
                await audio_message.clear_reactions()
                break
    except asyncio.TimeoutError:
        await voice_msg.delete(); await ctx.send("Tiempo de espera agotado.", delete_after=10)
    except Exception as e:
        await ctx.send("❌ Error durante el proceso de audiolab."); print(f"Error en !audiolab: {e}")
        
# --- MÓDULO DE GESTIÓN DE OPERADORES Y LM ---
@bot.command(name='apodo', help='Asigna un apodo a un usuario para un turno. Uso: !apodo <miembro> <dia|tarde|noche> <apodo>')
@commands.has_permissions(administrator=True)
async def apodo(ctx, miembro: discord.Member, turno: str, *, apodo_texto: str):
    turno = turno.lower()
    if turno not in ['dia', 'tarde', 'noche']:
        await ctx.send("❌ Turno inválido. Usa `dia`, `tarde` o `noche`."); return
    
    await db_execute(f"INSERT OR IGNORE INTO apodos_operador (user_id) VALUES (?)", (miembro.id,))
    await db_execute(f"UPDATE apodos_operador SET apodo_{turno} = ? WHERE user_id = ?", (apodo_texto, miembro.id))
    await ctx.send(f"✅ Apodo de {miembro.mention} para el turno de **{turno}** establecido como `{apodo_texto}`.")

@bot.command(name='verapodo', help='Muestra los apodos de un usuario.')
@commands.has_permissions(administrator=True)
async def verapodo(ctx, miembro: discord.Member):
    apodos = await db_execute("SELECT apodo_dia, apodo_tarde, apodo_noche FROM apodos_operador WHERE user_id = ?", (miembro.id,), fetch='one')
    embed = discord.Embed(title=f"Apodos de {miembro.name}", color=discord.Color.purple())
    if apodos:
        embed.add_field(name="Día ☀️", value=f"`{apodos[0]}`" if apodos[0] else "No asignado", inline=True)
        embed.add_field(name="Tarde 🌅", value=f"`{apodos[1]}`" if apodos[1] else "No asignado", inline=True)
        embed.add_field(name="Noche 🌑", value=f"`{apodos[2]}`" if apodos[2] else "No asignado", inline=True)
    else:
        embed.description = "Este usuario no tiene apodos asignados."
    await ctx.send(embed=embed)

@bot.command(name='quitarapodo', help='Elimina el apodo de un usuario para un turno. Uso: !quitarapodo <miembro> <dia|tarde|noche>')
@commands.has_permissions(administrator=True)
async def quitarapodo(ctx, miembro: discord.Member, turno: str):
    turno = turno.lower()
    if turno not in ['dia', 'tarde', 'noche']:
        await ctx.send("❌ Turno inválido. Usa `dia`, `tarde` o `noche`."); return
    
    rows = await db_execute(f"UPDATE apodos_operador SET apodo_{turno} = NULL WHERE user_id = ? AND apodo_{turno} IS NOT NULL", (miembro.id,))
    if rows > 0:
        await ctx.send(f"✅ Apodo de {miembro.mention} para el turno de **{turno}** eliminado.")
    else:
        await ctx.send(f"🤔 {miembro.mention} no tenía un apodo asignado para ese turno.")

@bot.command(name='listaapodos', help='Muestra una lista de todos los apodos asignados.')
@commands.has_permissions(administrator=True)
async def listaapodos(ctx):
    todos_los_apodos = await db_execute("SELECT user_id, apodo_dia, apodo_tarde, apodo_noche FROM apodos_operador", fetch='all')
    
    if not todos_los_apodos:
        await ctx.send("No hay apodos asignados a ningún operador."); return

    embed = discord.Embed(title="📋 Lista de Apodos de Operadores", color=discord.Color.purple())
    
    description = ""
    for user_id, apodo_dia, apodo_tarde, apodo_noche in todos_los_apodos:
        # No mostrar usuarios que no tienen ningún apodo asignado
        if not any([apodo_dia, apodo_tarde, apodo_noche]):
            continue
            
        miembro = ctx.guild.get_member(user_id)
        nombre_operador = miembro.mention if miembro else f"ID: {user_id}"
        
        dia_str = f"`{apodo_dia}`" if apodo_dia else "N/A"
        tarde_str = f"`{apodo_tarde}`" if apodo_tarde else "N/A"
        noche_str = f"`{apodo_noche}`" if apodo_noche else "N/A"
        
        description += f"**{nombre_operador}**\n"
        description += f"☀️ **Día:** {dia_str} | 🌅 **Tarde:** {tarde_str} | 🌑 **Noche:** {noche_str}\n\n"

    if not description:
        await ctx.send("No hay apodos asignados a ningún operador."); return

    if len(description) > 4000:
        description = description[:4000] + "\n\n*[Resultados truncados]*"
        
    embed.description = description
    await ctx.send(embed=embed)

@bot.command(name='asignar', help='Asigna perfiles a operadores. Uso: !asignar <@op1> <perfil1> [@op2 <perfil2>...]')
@commands.has_permissions(administrator=True)
async def asignar(ctx, *, args: str):
    parts = args.split()
    if len(parts) < 2 or len(parts) % 2 != 0:
        await ctx.send("❌ Formato incorrecto. Usa: `!asignar <@op1> <perfil1> [@op2 <perfil2>...]`"); return

    # Agrupar argumentos en pares de (mención, perfil)
    pares = []
    for i in range(0, len(parts), 2):
        pares.append((parts[i], parts[i+1].lower()))

    # Verificar que todos los perfiles a asignar existen
    perfiles_a_verificar = list(set([p[1] for p in pares]))
    placeholders = ','.join('?' for _ in perfiles_a_verificar)
    perfiles_existentes_rows = await db_execute(f"SELECT nombre FROM personas WHERE nombre IN ({placeholders})", tuple(perfiles_a_verificar), fetch='all')
    nombres_perfiles_existentes = {row[0] for row in perfiles_existentes_rows}
    
    perfiles_no_encontrados = [p for p in perfiles_a_verificar if p not in nombres_perfiles_existentes]
    if perfiles_no_encontrados:
        await ctx.send(f"❌ Los siguientes perfiles no existen: `{', '.join(perfiles_no_encontrados)}`. Créalos primero con `!crearperfil`."); return

    # Asignar perfiles
    reporte = ""
    for mencion, perfil in pares:
        try:
            miembro = await commands.MemberConverter().convert(ctx, mencion)
            await db_execute("INSERT INTO operador_perfil (user_id, nombre_perfil) VALUES (?, ?)", (miembro.id, perfil))
            reporte += f"✅ **Asignado a {miembro.mention}**: `{perfil}`\n"
        except commands.MemberNotFound:
            reporte += f"⚠️ **No se encontró al miembro**: `{mencion}`\n"
        except sqlite3.IntegrityError:
            reporte += f"🤔 **Ya asignado a {mencion}**: `{perfil}`\n"
        except Exception as e:
            reporte += f"❌ **Error con {mencion} y {perfil}**: {e}\n"

    embed = discord.Embed(title="📝 Reporte de Asignación", color=discord.Color.blue())
    embed.description = reporte if reporte else "No se realizaron asignaciones."
    await ctx.send(embed=embed)

@bot.command(name='desasignar', help='Quita perfiles a operadores. Uso: !desasignar <@op1> <perfil1> [@op2 <perfil2>...]')
@commands.has_permissions(administrator=True)
async def desasignar(ctx, *, args: str):
    parts = args.split()
    if len(parts) < 2 or len(parts) % 2 != 0:
        await ctx.send("❌ Formato incorrecto. Usa: `!desasignar <@op1> <perfil1> [@op2 <perfil2>...]`"); return

    pares = []
    for i in range(0, len(parts), 2):
        pares.append((parts[i], parts[i+1].lower()))

    reporte = ""
    for mencion, perfil in pares:
        try:
            miembro = await commands.MemberConverter().convert(ctx, mencion)
            rows = await db_execute("DELETE FROM operador_perfil WHERE user_id = ? AND nombre_perfil = ?", (miembro.id, perfil))
            if rows > 0:
                reporte += f"✅ **Desasignado de {miembro.mention}**: `{perfil}`\n"
            else:
                reporte += f"🤔 **{miembro.mention} no tenía asignado**: `{perfil}`\n"
        except commands.MemberNotFound:
            reporte += f"⚠️ **No se encontró al miembro**: `{mencion}`\n"
        except Exception as e:
            reporte += f"❌ **Error con {mencion} y {perfil}**: {e}\n"

    embed = discord.Embed(title="📝 Reporte de Desasignación", color=discord.Color.orange())
    embed.description = reporte if reporte else "No se realizaron desasignaciones."
    await ctx.send(embed=embed)

@bot.command(name='sincronizar-perfiles', help='Asigna TODOS los perfiles a TODOS los operadores del servidor.')
@commands.has_permissions(administrator=True)
async def sincronizar_perfiles(ctx):
    """Asigna todos los perfiles existentes a todos los miembros no bots del servidor."""
    await ctx.send("⏳ Iniciando sincronización masiva... Esto puede tardar un momento.")
    
    async with ctx.typing():
        # 1. Obtener todos los perfiles
        perfiles_rows = await db_execute("SELECT nombre FROM personas", fetch='all')
        if not perfiles_rows:
            await ctx.send("❌ No hay perfiles creados para asignar."); return
        perfiles_lista = [row[0] for row in perfiles_rows]

        # 2. Obtener todos los operadores (miembros no bots)
        operadores = [m for m in ctx.guild.members if not m.bot]
        if not operadores:
            await ctx.send("❌ No se encontraron operadores en el servidor."); return

        # 3. Asignar perfiles
        nuevas_asignaciones = 0
        for operador in operadores:
            for perfil in perfiles_lista:
                # Usamos INSERT OR IGNORE para evitar errores si la asignación ya existe.
                rows_affected = await db_execute("INSERT OR IGNORE INTO operador_perfil (user_id, nombre_perfil) VALUES (?, ?)", (operador.id, perfil))
                if rows_affected > 0:
                    nuevas_asignaciones += 1
    
    await ctx.send(f"✅ Sincronización completada. Se realizaron **{nuevas_asignaciones}** nuevas asignaciones a **{len(operadores)}** operadores.")

@bot.command(name='desincronizar-perfiles', help='(PELIGRO) Elimina TODAS las asignaciones de perfiles.')
@commands.has_permissions(administrator=True)
async def desincronizar_perfiles(ctx):
    """Elimina todas las asignaciones de perfiles de todos los operadores. Requiere confirmación."""
    
    embed = discord.Embed(
        title="⚠️ ADVERTENCIA DE SEGURIDAD ⚠️",
        description="Estás a punto de **eliminar TODAS las asignaciones de perfiles** para TODOS los operadores. Esta acción no se puede deshacer.\n\nReacciona con ✅ para confirmar en los próximos 30 segundos.",
        color=discord.Color.red()
    )
    confirm_msg = await ctx.send(embed=embed)
    await confirm_msg.add_reaction("✅")
    await confirm_msg.add_reaction("❌")

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id

    try:
        reaction, _ = await bot.wait_for('reaction_add', timeout=30.0, check=check)
        
        if str(reaction.emoji) == "✅":
            await confirm_msg.edit(content="⏳ Procediendo con la desincronización masiva...", embed=None)
            
            rows_deleted = await db_execute("DELETE FROM operador_perfil")
            
            await confirm_msg.edit(content=f"✅ Desincronización completada. Se eliminaron **{rows_deleted}** asignaciones de perfiles.")
            await confirm_msg.clear_reactions()
        else:
            await confirm_msg.edit(content="❌ Operación cancelada.", embed=None)
            await confirm_msg.clear_reactions()

    except asyncio.TimeoutError:
        await confirm_msg.edit(content="❌ Tiempo de espera agotado. Operación cancelada.", embed=None)
        await confirm_msg.clear_reactions()

@bot.command(name='misperfiles', help='Muestra los perfiles asignados. Uso: !misperfiles [miembro]')
async def misperfiles(ctx, miembro: discord.Member = None):
    target_user = miembro or ctx.author
    perfiles = await db_execute("SELECT nombre_perfil FROM operador_perfil WHERE user_id = ? ORDER BY nombre_perfil ASC", (target_user.id,), fetch='all')
    
    if perfiles:
        lista_perfiles = "\n".join([f"- `{p[0]}`" for p in perfiles])
        embed = discord.Embed(title=f"Perfiles de {target_user.name}", description=lista_perfiles, color=discord.Color.blue())
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"🤔 {target_user.name} no tiene perfiles asignados.")

@bot.command(name='lm', help='Formatea y envía un LM. Uso: !lm <perfil> <mensaje>')
async def lm(ctx, nombre_perfil: str, *, mensaje: str):
    nombre_perfil = nombre_perfil.lower()
    
    # 1. Verificar que el operador tiene asignado ese perfil
    asignacion = await db_execute("SELECT 1 FROM operador_perfil WHERE user_id = ? AND nombre_perfil = ?", (ctx.author.id, nombre_perfil), fetch='one')
    if not asignacion:
        await ctx.send(f"❌ No tienes asignado el perfil `{nombre_perfil}`. Usa `!misperfiles` para ver tus perfiles."); return

    # 2. Obtener el número de cambio y registrar el LM
    today_str = date.today().isoformat()
    turno_key = get_turno_key()
    
    # Contar los LMs de este turno para obtener el número de cambio
    count_row = await db_execute("SELECT COUNT(*) FROM lm_logs WHERE DATE(timestamp) = ? AND turno = ?", (today_str, turno_key), fetch='one')
    cambio_num = count_row[0] + 1
    
    # Registrar este nuevo LM en el log, incluyendo el contenido del mensaje
    await db_execute("INSERT INTO lm_logs (user_id, perfil_usado, message_content, timestamp, turno) VALUES (?, ?, ?, ?, ?)", (ctx.author.id, nombre_perfil, mensaje, datetime.now(), turno_key))

    # 3. Calcular el rango de hora
    now = datetime.now()
    h1_dt = now
    h2_dt = now + timedelta(hours=1)
    h1_str = h1_dt.strftime('%#I' if os.name != 'nt' else '%I').lstrip('0') + h1_dt.strftime('%p').lower()
    h2_str = h2_dt.strftime('%#I' if os.name != 'nt' else '%I').lstrip('0') + h2_dt.strftime('%p').lower()
    time_range = f"{h1_str} - {h2_str}"

    # 4. Obtener apodo del operador para el turno actual
    apodo_row = await db_execute(f"SELECT apodo_{turno_key} FROM apodos_operador WHERE user_id = ?", (ctx.author.id,), fetch='one')
    operador_name = apodo_row[0] if apodo_row and apodo_row[0] else ctx.author.name

    # 5. Construir y enviar el mensaje final
    perfil_operador_str = f"{nombre_perfil.title()}/ {operador_name}"
    
    mensaje_final = (
        f"Cambio# {cambio_num} ({TURNOS_DISPLAY.get(turno_key)})   {time_range}\n"
        f"{perfil_operador_str}\n\n"
        f"😎 {mensaje}"
    )
    
    try:
        await ctx.message.delete()
        await ctx.send(mensaje_final)
    except discord.Forbidden:
        await ctx.send("⚠️ No tengo permisos para borrar tu comando, pero aquí está tu LM:")
        await ctx.send(mensaje_final)
    except Exception as e:
        await ctx.send(f"❌ Ocurrió un error inesperado al enviar el LM. Error: {e}")

# --- MÓDULO DE ESTADÍSTICAS ---
@bot.command(name='estadisticas', aliases=['stats'], help='Muestra estadísticas de LM. Uso: !stats [periodo] [filtro]')
@commands.has_permissions(administrator=True)
async def estadisticas(ctx, periodo: str = 'hoy', *, filtro: str = None):
    # --- 1. Parsear el periodo de tiempo ---
    where_clauses = []
    params = []
    title = ""
    periodo = periodo.lower()

    today = date.today()
    if periodo == 'hoy':
        where_clauses.append("DATE(timestamp) = ?")
        params.append(today.isoformat())
        title = "Estadísticas de Hoy"
    elif periodo == 'ayer':
        ayer = today - timedelta(days=1)
        where_clauses.append("DATE(timestamp) = ?")
        params.append(ayer.isoformat())
        title = f"Estadísticas de Ayer ({ayer.strftime('%d-%m-%Y')})"
    elif periodo == 'semana':
        where_clauses.append("strftime('%Y-%W', timestamp) = strftime('%Y-%W', 'now', 'localtime')")
        title = "Estadísticas de esta Semana"
    elif periodo == 'semana-anterior':
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        where_clauses.append("DATE(timestamp) BETWEEN ? AND ?")
        params.extend([last_monday.isoformat(), last_sunday.isoformat()])
        title = f"Estadísticas de la Semana Anterior ({last_monday.strftime('%d/%m')} - {last_sunday.strftime('%d/%m')})"
    elif periodo == 'mes':
        where_clauses.append("strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now', 'localtime')")
        title = "Estadísticas de este Mes"
    elif periodo == 'mes-anterior':
        first_day_current_month = today.replace(day=1)
        last_day_prev_month = first_day_current_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        where_clauses.append("DATE(timestamp) BETWEEN ? AND ?")
        params.extend([first_day_prev_month.isoformat(), last_day_prev_month.isoformat()])
        title = f"Estadísticas del Mes Anterior ({first_day_prev_month.strftime('%B %Y')})"
    elif ' a ' in periodo:
        try:
            start_date_str, end_date_str = [p.strip() for p in periodo.split(' a ')]
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            where_clauses.append("DATE(timestamp) BETWEEN ? AND ?")
            params.extend([start_date.isoformat(), end_date.isoformat()])
            title = f"Estadísticas de {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        except (ValueError, IndexError):
            await ctx.send("❌ Formato de rango de fechas incorrecto. Usa `AAAA-MM-DD a AAAA-MM-DD`."); return
    else:
        try:
            fecha_obj = datetime.strptime(periodo, '%Y-%m-%d').date()
            where_clauses.append("DATE(timestamp) = ?")
            params.append(fecha_obj.isoformat())
            title = f"Estadísticas del {fecha_obj.strftime('%d-%m-%Y')}"
        except ValueError:
            await ctx.send("❌ Periodo no válido. Usa `hoy`, `ayer`, `semana`, `mes`, `semana-anterior`, `mes-anterior`, una fecha `AAAA-MM-DD` o un rango `AAAA-MM-DD a AAAA-MM-DD`."); return

    # --- 2. Parsear el filtro (opcional) ---
    if filtro:
        filtro_lower = filtro.lower()
        if filtro_lower in ['dia', 'tarde', 'noche']:
            where_clauses.append("turno = ?")
            params.append(filtro_lower)
            title += f" (Turno: {filtro_lower.title()})"
        else:
            try:
                miembro = await commands.MemberConverter().convert(ctx, filtro)
                where_clauses.append("user_id = ?")
                params.append(miembro.id)
                title += f" (Operador: {miembro.display_name})"
            except commands.MemberNotFound:
                user_ids_rows = await db_execute("SELECT user_id FROM apodos_operador WHERE apodo_dia LIKE ? OR apodo_tarde LIKE ? OR apodo_noche LIKE ?", (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'), fetch='all')
                if user_ids_rows:
                    ids = [row[0] for row in user_ids_rows]
                    placeholders = ','.join('?' for _ in ids)
                    where_clauses.append(f"user_id IN ({placeholders})")
                    params.extend(ids)
                    title += f" (Apodo: {filtro})"
                else:
                    await ctx.send(f"🤔 No encontré ningún operador con la mención o apodo `{filtro}`."); return

    # --- 3. Construir y ejecutar la consulta ---
    query = f"SELECT user_id, turno, COUNT(*) FROM lm_logs WHERE {' AND '.join(where_clauses)} GROUP BY user_id, turno ORDER BY COUNT(*) DESC"
    results = await db_execute(query, tuple(params), fetch='all')

    # --- 4. Formatear y enviar los resultados ---
    embed = discord.Embed(title=f"📊 {title}", color=discord.Color.green())
    if not results:
        embed.description = "No se encontraron registros para los criterios seleccionados."
        await ctx.send(embed=embed); return

    total_lms = sum(count for _, _, count in results)
    embed.description = f"**Total de LMs:** {total_lms}\n\n**Desglose por Operador y Turno:**"

    stats_by_user = {}
    for user_id, turno, count in results:
        if user_id not in stats_by_user:
            stats_by_user[user_id] = {'total': 0, 'turnos': {}}
        stats_by_user[user_id]['total'] += count
        stats_by_user[user_id]['turnos'][turno] = count

    sorted_users = sorted(stats_by_user.items(), key=lambda item: item[1]['total'], reverse=True)

    description_body = ""
    for user_id, data in sorted_users:
        miembro = ctx.guild.get_member(user_id)
        nombre_operador = miembro.mention if miembro else f"ID: {user_id}"
        
        turnos_str_parts = []
        if 'dia' in data['turnos']: turnos_str_parts.append(f"☀️ {data['turnos']['dia']}")
        if 'tarde' in data['turnos']: turnos_str_parts.append(f"🌅 {data['turnos']['tarde']}")
        if 'noche' in data['turnos']: turnos_str_parts.append(f"🌑 {data['turnos']['noche']}")
        turnos_str = ' | '.join(turnos_str_parts)

        description_body += f"**{nombre_operador}**: {data['total']} LMs en total ({turnos_str})\n"
    
    embed.description += "\n" + description_body
    if len(embed.description) > 4000:
        embed.description = embed.description[:4000] + "\n\n*[Resultados truncados]*"

    await ctx.send(embed=embed)

@bot.command(name='registrolm', aliases=['verlms'], help='Muestra los LMs enviados. Uso: !registrolm [periodo] [filtro]')
@commands.has_permissions(administrator=True)
async def registrolm(ctx, periodo: str = 'hoy', *, filtro: str = None):
    # --- 1. Parsear el periodo de tiempo (reutilizado de !estadisticas) ---
    where_clauses = []
    params = []
    title = ""
    periodo = periodo.lower()

    today = date.today()
    if periodo == 'hoy':
        where_clauses.append("DATE(timestamp) = ?")
        params.append(today.isoformat())
        title = "Registro de LMs de Hoy"
    elif periodo == 'ayer':
        ayer = today - timedelta(days=1)
        where_clauses.append("DATE(timestamp) = ?")
        params.append(ayer.isoformat())
        title = f"Registro de LMs de Ayer ({ayer.strftime('%d-%m-%Y')})"
    elif periodo == 'semana':
        where_clauses.append("strftime('%Y-%W', timestamp) = strftime('%Y-%W', 'now', 'localtime')")
        title = "Registro de LMs de esta Semana"
    elif periodo == 'semana-anterior':
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        where_clauses.append("DATE(timestamp) BETWEEN ? AND ?")
        params.extend([last_monday.isoformat(), last_sunday.isoformat()])
        title = f"Registro de LMs de la Semana Anterior ({last_monday.strftime('%d/%m')} - {last_sunday.strftime('%d/%m')})"
    elif periodo == 'mes':
        where_clauses.append("strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now', 'localtime')")
        title = "Registro de LMs de este Mes"
    elif periodo == 'mes-anterior':
        first_day_current_month = today.replace(day=1)
        last_day_prev_month = first_day_current_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        where_clauses.append("DATE(timestamp) BETWEEN ? AND ?")
        params.extend([first_day_prev_month.isoformat(), last_day_prev_month.isoformat()])
        title = f"Registro de LMs del Mes Anterior ({first_day_prev_month.strftime('%B %Y')})"
    elif ' a ' in periodo:
        try:
            start_date_str, end_date_str = [p.strip() for p in periodo.split(' a ')]
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            where_clauses.append("DATE(timestamp) BETWEEN ? AND ?")
            params.extend([start_date.isoformat(), end_date.isoformat()])
            title = f"Registro de LMs de {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        except (ValueError, IndexError):
            await ctx.send("❌ Formato de rango de fechas incorrecto. Usa `AAAA-MM-DD a AAAA-MM-DD`."); return
    else:
        try:
            fecha_obj = datetime.strptime(periodo, '%Y-%m-%d').date()
            where_clauses.append("DATE(timestamp) = ?")
            params.append(fecha_obj.isoformat())
            title = f"Registro de LMs del {fecha_obj.strftime('%d-%m-%Y')}"
        except ValueError:
            await ctx.send("❌ Periodo no válido. Usa `hoy`, `ayer`, `semana`, `mes`, `semana-anterior`, `mes-anterior`, una fecha `AAAA-MM-DD` o un rango `AAAA-MM-DD a AAAA-MM-DD`."); return

    # --- 2. Parsear el filtro (opcional) (reutilizado de !estadisticas) ---
    if filtro:
        filtro_lower = filtro.lower()
        if filtro_lower in ['dia', 'tarde', 'noche']:
            where_clauses.append("turno = ?")
            params.append(filtro_lower)
            title += f" (Turno: {filtro_lower.title()})"
        else:
            try:
                miembro = await commands.MemberConverter().convert(ctx, filtro)
                where_clauses.append("user_id = ?")
                params.append(miembro.id)
                title += f" (Operador: {miembro.display_name})"
            except commands.MemberNotFound:
                user_ids_rows = await db_execute("SELECT user_id FROM apodos_operador WHERE apodo_dia LIKE ? OR apodo_tarde LIKE ? OR apodo_noche LIKE ?", (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'), fetch='all')
                if user_ids_rows:
                    ids = [row[0] for row in user_ids_rows]
                    placeholders = ','.join('?' for _ in ids)
                    where_clauses.append(f"user_id IN ({placeholders})")
                    params.extend(ids)
                    title += f" (Apodo: {filtro})"
                else:
                    await ctx.send(f"🤔 No encontré ningún operador con la mención o apodo `{filtro}`."); return

    # --- 3. Construir y ejecutar la consulta ---
    query = f"SELECT user_id, perfil_usado, message_content, timestamp FROM lm_logs WHERE {' AND '.join(where_clauses)} ORDER BY timestamp DESC"
    results = await db_execute(query, tuple(params), fetch='all')

    # --- 4. Formatear y enviar los resultados ---
    embed = discord.Embed(title=f"📜 {title}", color=discord.Color.orange())
    if not results:
        embed.description = "No se encontraron LMs para los criterios seleccionados."
        await ctx.send(embed=embed); return

    description = ""
    for user_id, perfil, mensaje, ts in results:
        miembro = ctx.guild.get_member(user_id)
        nombre_operador = miembro.mention if miembro else f"ID: {user_id}"
        
        log_entry = (
            f"**[{ts.strftime('%H:%M')}] - Perfil: `{perfil}` | Op: {nombre_operador}**\n"
            f"> {mensaje}\n\n"
        )
        
        if len(description) + len(log_entry) > 4000:
            description += "*[Resultados truncados por su longitud]*"
            break
        description += log_entry
        
    embed.description = description
    await ctx.send(embed=embed)

# --- MÓDULO DE MIGRACIÓN DE DATOS ---
TABLES_TO_MIGRATE = [
    'personas', 'datos_persona', 'reglas_ia', 
    'permisos_comandos', 'comandos_config', 
    'operador_perfil', 'apodos_operador', 'comandos_dinamicos'
]

@bot.command(name='exportar-config', help='(Dueño) Exporta la configuración crítica a un archivo JSON.')
@commands.is_owner()
async def exportar_config(ctx):
    await ctx.send("⏳ Exportando configuración... por favor espera.")
    data_to_export = {}
    
    try:
        with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            for table_name in TABLES_TO_MIGRATE:
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                data_to_export[table_name] = [dict(row) for row in rows]

        json_data = json.dumps(data_to_export, indent=4)
        
        buffer = io.BytesIO(json_data.encode('utf-8'))
        file = discord.File(buffer, filename=f'config_backup_{date.today().isoformat()}.json')
        await ctx.send("✅ ¡Configuración exportada! Guarda este archivo para futuras importaciones.", file=file)

    except Exception as e:
        await ctx.send(f"❌ Ocurrió un error durante la exportación: {e}")

@bot.command(name='importar-config', help='(Dueño) Importa la configuración desde un archivo JSON.')
@commands.is_owner()
async def importar_config(ctx):
    if not ctx.message.attachments:
        await ctx.send("❌ Debes adjuntar el archivo `config_backup.json` para importar."); return

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith('.json'):
        await ctx.send("❌ El archivo debe ser de tipo JSON."); return

    await ctx.send("⏳ Importando configuración... por favor espera. **No ejecutes otros comandos.**")
    
    try:
        json_bytes = await attachment.read()
        data_to_import = json.loads(json_bytes.decode('utf-8'))

        report = ""
        with sqlite3.connect('memoria_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            cursor = conn.cursor()
            for table_name in TABLES_TO_MIGRATE:
                if table_name in data_to_import:
                    rows = data_to_import[table_name]
                    if not rows: continue
                    
                    count = 0
                    for row in rows:
                        columns = ', '.join(row.keys())
                        placeholders = ', '.join('?' for _ in row)
                        query = f"INSERT OR REPLACE INTO {table_name} ({columns}) VALUES ({placeholders})"
                        cursor.execute(query, tuple(row.values()))
                        count += 1
                    report += f"✅ Tabla `{table_name}`: Se importaron {count} registros.\n"
        
        embed = discord.Embed(title="✅ Reporte de Importación", description=report, color=discord.Color.green())
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Ocurrió un error durante la importación: {e}")

# --- MÓDULO DE TAREAS PROGRAMADAS ---
@tasks.loop(seconds=60)
async def check_scheduled_tasks():
    now = datetime.now()
    # sent = 0 (pendiente), 1 (enviado), 2 (fallido)
    tasks_to_run = await db_execute("SELECT id, channel_id, author_id, message_content FROM tareas_programadas WHERE send_at <= ? AND sent = 0", (now,), fetch='all')
    for task_id, channel_id, author_id, message_content in tasks_to_run:
        channel = bot.get_channel(channel_id)
        if channel:
            try:
                await channel.send(message_content)
               
               
                await db_execute("UPDATE tareas_programadas SET sent = 1 WHERE id = ?", (task_id,))
            except Exception as e:
                print(f"Error al enviar tarea programada {task_id} al canal {channel_id}: {e}")
        else:
            await db_execute("UPDATE tareas_programadas SET sent = 2 WHERE id = ?", (task_id,))
            print(f"No se pudo encontrar el canal {channel_id} para la tarea {task_id}. Marcada como fallida.")

@check_scheduled_tasks.before_loop
async def before_check_scheduled_tasks():
    await bot.wait_until_ready()

@bot.command(name='programar', help='Programa un mensaje. Uso: !programar <#canal> "AAAA-MM-DD HH:MM" <mensaje>')
@commands.has_permissions(administrator=True)
async def programar(ctx, canal: discord.TextChannel, fecha_hora_str: str, *, mensaje: str):
    try:
        send_time = datetime.strptime(fecha_hora_str, '%Y-%m-%d %H:%M')
    except ValueError:
        await ctx.send("❌ Formato de fecha y hora incorrecto. Usa `AAAA-MM-DD HH:MM`."); return

    if send_time <= datetime.now():
        await ctx.send("❌ La fecha y hora deben ser en el futuro."); return

    await db_execute(
        "INSERT INTO tareas_programadas (guild_id, channel_id, author_id, message_content, send_at) VALUES (?, ?, ?, ?, ?)",
        (ctx.guild.id, canal.id, ctx.author.id, mensaje, send_time)
    )
    
    last_task = await db_execute("SELECT id FROM tareas_programadas ORDER BY id DESC LIMIT 1", fetch='one')
    task_id = last_task[0] if last_task else 'desconocido'

    await ctx.send(f"✅ ¡Mensaje programado! Se enviará en {canal.mention} el `{send_time.strftime('%Y-%m-%d a las %H:%M')}`. **ID de tarea: {task_id}**")

@bot.command(name='programar-serie', help='Genera y programa una serie de posts. Uso: !programar-serie <#canal> <cantidad> "AAAA-MM-DD HH:MM" <tema>')
@commands.has_permissions(administrator=True)
async def programar_serie(ctx, canal: discord.TextChannel, cantidad: int, fecha_hora_inicio_str: str, *, tema: str):
    if not (1 < cantidad <= 10):
        await ctx.send("❌ La cantidad de posts debe estar entre 2 y 10."); return
    
    try:
        start_time = datetime.strptime(fecha_hora_inicio_str, '%Y-%m-%d %H:%M')
    except ValueError:
        await ctx.send("❌ Formato de fecha y hora incorrecto. Usa `AAAA-MM-DD HH:MM`."); return

    if start_time <= datetime.now():
        await ctx.send("❌ La fecha y hora de inicio deben ser en el futuro."); return

    await ctx.send(f"🧠 Entendido. Generando una serie de **{cantidad} posts** sobre '{tema}'. Esto puede tardar un momento...")
    async with ctx.typing():
        try:
            prompt_serie = f"""**TAREA:** Eres un creador de contenido experto. Genera una serie de {cantidad} publicaciones cortas y atractivas sobre el tema "{tema}".
**REGLAS CRÍTICAS DE FORMATO:**
1.  Cada publicación debe ser un texto completo y coherente por sí mismo.
2.  Separa CADA publicación con el delimitador exacto y único: `|||---|||`
3.   No añadas números de lista (como 1., 2.) ni ningún otro texto introductorio o de cierre. Solo las publicaciones y el delimitador."""

            response = await gemini_model.generate_content_async(prompt_serie)
            posts = response.text.split('|||---|||')

            if len(posts) < cantidad:
                await ctx.send(f"⚠️ La IA generó menos posts de los solicitados ({len(posts)} de {cantidad}). Inténtalo de nuevo o con un tema diferente."); return

            created_tasks_ids = []
            for i, post_content in enumerate(posts[:cantidad]):
                send_time = start_time + timedelta(days=i)
                await db_execute(
                    "INSERT INTO tareas_programadas (guild_id, channel_id, author_id, message_content, send_at) VALUES (?, ?, ?, ?, ?)",
                    (ctx.guild.id, canal.id, ctx.author.id, post_content.strip(), send_time)
                )
                last_task = await db_execute("SELECT id FROM tareas_programadas ORDER BY id DESC LIMIT 1", fetch='one')
                if last_task: created_tasks_ids.append(str(last_task[0]))

            await ctx.send(f"✅ ¡Serie de {len(created_tasks_ids)} posts generada y programada en {canal.mention}! IDs de tarea: `{', '.join(created_tasks_ids)}`")

        except Exception as e:
            await ctx.send("❌ Error al generar la serie de contenido con la IA.")
            print(f"Error en !programar-serie: {e}")

@bot.command(name='programar-ia', aliases=['programaria'], help='Genera y programa contenido con IA. Uso: !programar-ia <#canal> "AAAA-MM-DD HH:MM" <prompt>')
@commands.has_permissions(administrator=True)
async def programar_ia(ctx, canal: discord.TextChannel, fecha_hora_str: str, *, prompt: str):
    try:
        send_time = datetime.strptime(fecha_hora_str, '%Y-%m-%d %H:%M')
    except ValueError:
        await ctx.send("❌ Formato de fecha y hora incorrecto. Usa `AAAA-MM-DD HH:MM`."); return

    if send_time <= datetime.now():
        await ctx.send("❌ La fecha y hora deben ser en el futuro."); return

    await ctx.send(f"🧠 Entendido. Generando y programando contenido con IA...")
    async with ctx.typing():
        try:
            # Generar el contenido con Gemini
            response = await gemini_model.generate_content_async(prompt)
            mensaje_generado = response.text

            # Guardar la tarea en la base de datos
            await db_execute(
                "INSERT INTO tareas_programadas (guild_id, channel_id, author_id, message_content, send_at) VALUES (?, ?, ?, ?, ?)",
                (ctx.guild.id, canal.id, ctx.author.id, mensaje_generado, send_time)
            )
            
            last_task = await db_execute("SELECT id FROM tareas_programadas ORDER BY id DESC LIMIT 1", fetch='one')
            task_id = last_task[0] if last_task else 'desconocido'

            await ctx.send(f"✅ ¡Contenido generado y programado! Se enviará en {canal.mention} el `{send_time.strftime('%Y-%m-%d a las %H:%M')}`. **ID de tarea: {task_id}**")
        except Exception as e:
            await ctx.send("❌ Error al generar o programar el contenido con la IA.")
            print(f"Error en !programar-ia: {e}")

@bot.command(name='tareas', help='Muestra los mensajes programados pendientes.')
@commands.has_permissions(administrator=True)
async def tareas(ctx):
    pending_tasks = await db_execute("SELECT id, channel_id, author_id, send_at, message_content FROM tareas_programadas WHERE sent = 0 AND guild_id = ? ORDER BY send_at ASC", (ctx.guild.id,), fetch='all')
    if not pending_tasks:
        await ctx.send("No hay tareas programadas pendientes."); return

    embed = discord.Embed(title="🗓️ Tareas Programadas Pendientes", color=discord.Color.gold())
    description = ""
    for task_id, channel_id, author_id, send_at_str, message in pending_tasks:
        channel = bot.get_channel(channel_id)
        author = bot.get_user(author_id)
        channel_mention = channel.mention if channel else f"ID: {channel_id}"
        author_name = author.name if author else f"ID: {author_id}"
        send_at = datetime.fromisoformat(send_at_str)
        description += f"**ID: {task_id}** | {channel_mention} | Por: `{author_name}` | `{send_at.strftime('%Y-%m-%d %H:%M')}`\n"
        description += f"```{message[:100]}{'...' if len(message) > 100 else ''}```\n"
    
    if len(description) > 4000:
        description = description[:4000] + "\n\n*[Resultados truncados]*"

    embed.description = description
    await ctx.send(embed=embed)

@bot.command(name='borrartarea', help='Borra una tarea programada por su ID.')
@commands.has_permissions(administrator=True)
async def borrartarea(ctx, task_id: int):
    rows = await db_execute("DELETE FROM tareas_programadas WHERE id = ? AND guild_id = ?", (task_id, ctx.guild.id))
    if rows > 0:
        await ctx.send(f"✅ Tarea con ID `{task_id}` eliminada.")
    else:
        await ctx.send(f"🤔 No encontré una tarea pendiente con el ID `{task_id}` en este servidor.")
        
# --- Comandos Utilitarios y Dinámicos ---
@bot.command(name='crearcomando', help='Crea un comando personalizado.')
@commands.has_permissions(administrator=True)
async def crear_comando(ctx, nombre: str, *, respuesta: str):
    await db_execute("INSERT OR REPLACE INTO comandos_dinamicos (nombre_comando, respuesta_comando, creador_id, creador_nombre) VALUES (?, ?, ?, ?)", (nombre.lower(), respuesta, ctx.author.id, ctx.author.name))
    bot.dynamic_commands[nombre.lower()] = respuesta 
    await ctx.send(f"✅ ¡Comando `!{nombre.lower()}` creado/actualizado!")

@bot.command(name='borrarcomando', help='Borra un comando personalizado.')
@commands.has_permissions(administrator=True)
async def borrar_comando(ctx, nombre: str):
    nombre = nombre.lower()
    rows = await db_execute("DELETE FROM comandos_dinamicos WHERE nombre_comando = ?", (nombre,))
    if rows > 0:
        if nombre in bot.dynamic_commands: del bot.dynamic_commands[nombre]
        await ctx.send(f"✅ ¡Comando `!{nombre}` borrado!")
    else:
        await ctx.send(f"🤔 No encontré un comando personalizado llamado `{nombre}`.")

@bot.command(name='anuncio', help='Envía un anuncio. Uso: !anuncio <#canal...|todos|categoria> <mensaje>')
@commands.has_permissions(administrator=True)
async def anuncio(ctx, *, args: str):
    if not args:
        await ctx.send("❌ Faltan argumentos. Uso: `!anuncio <#canal... | todos | categoria> <mensaje>`"); return

    parts = args.split()
    canales_destino = []
    mensaje_str = ""

    # Prioridad 1: Menciones de canal explícitas
    if ctx.message.channel_mentions:
        canales_destino = ctx.message.channel_mentions
        mensaje_str_reconstruido = args
        for mention in ctx.message.channel_mentions:
            mensaje_str_reconstruido = mensaje_str_reconstruido.replace(mention.mention, "").strip()
        mensaje_str = mensaje_str_reconstruido
    
    # Prioridad 2: Palabras clave ('todos' o nombre de categoría)
    else:
        target = parts[0]
        
        # Subcaso 2.1: 'todos'
        if target.lower() == 'todos':
            canales_destino = [ch for ch in ctx.guild.text_channels if ch.permissions_for(ctx.guild.me).send_messages]
            mensaje_str = " ".join(parts[1:])
        
        # Subcaso 2.2: Nombre de categoría (con soporte para nombres largos y caracteres especiales)
        else:
            categoria_encontrada = None
            mensaje_encontrado = ""
            
            # Ordenar categorías por longitud de nombre (de más largo a más corto) para encontrar la mejor coincidencia
            sorted_categories = sorted(ctx.guild.categories, key=lambda c: len(c.name), reverse=True)
            
            for categoria in sorted_categories:
                # Normalizar tanto el nombre de la categoría como el input del usuario para una comparación robusta
                cat_name_normalized = unidecode(categoria.name).lower()
                args_normalized = unidecode(args).lower()
                
                if args_normalized.startswith(cat_name_normalized):
                    categoria_encontrada = categoria
                    # El mensaje es lo que queda después del nombre de la categoría
                    mensaje_encontrado = args[len(categoria.name):].strip()
                    break

            if categoria_encontrada:
                canales_destino = [ch for ch in categoria_encontrada.text_channels if ch.permissions_for(ctx.guild.me).send_messages]
                mensaje_str = mensaje_encontrado
            else:
                await ctx.send(f"❌ No se encontró el objetivo. Debe ser una mención de canal, la palabra `todos` o el nombre de una categoría existente."); return

    if not canales_destino:
        await ctx.send("❌ No se encontraron canales de destino válidos o no tengo permisos para verlos/enviar mensajes."); return
    
    if not mensaje_str:
        await ctx.send("❌ El mensaje no puede estar vacío."); return

    sent_count = 0
    for canal in canales_destino:
        try:
            await canal.send(mensaje_str)
            sent_count += 1
        except Exception as e:
            print(f"No se pudo enviar a {canal.name}: {e}")
    
    await ctx.message.add_reaction('✅')
    if sent_count > 0:
        await ctx.send(f"✅ Anuncio enviado a {sent_count} canal(es).", delete_after=10)

@bot.command(name='saludar', help='Un simple saludo.')
async def saludar(ctx):
    await ctx.send(f'¡Hola, {ctx.author.name}! Estoy listo para tus órdenes.')
    
@bot.command(name='preguntar', help='Pregúntale algo a la IA.')
async def preguntar(ctx, *, pregunta: str):
    async with ctx.typing():
        try:
            response = await gemini_model.generate_content_async(pregunta)
            await ctx.send(response.text)
        except Exception as e:
            await ctx.send("❌ Error con la IA de Gemini."); print(f"Error en !preguntar: {e}")

# --- Función para mantener el bot activo en Replit ---
app = Flask('')

@app.route('/')
def home():
    return "Estoy vivo."

def run():
  app.run(host='0.0.0.0',port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- Ejecución del Bot ---
if __name__ == "__main__":
    if DISCORD_TOKEN:
        print("--- [FASE 0.5] Iniciando servidor web para mantener activo... ---")
        keep_alive()
        print("--- [FASE 0.6] Ejecutando bot.run() ---")
        bot.run(DISCORD_TOKEN)
    else:
        print("--- [ERROR CRÍTICO] DISCORD_TOKEN no encontrado.")
