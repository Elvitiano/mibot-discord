import discord
from discord.ext import commands
from datetime import datetime, date, timedelta
import os
import pytz
from utils.db_manager import db_execute
from utils.helpers import get_turno_key, TURNOS_DISPLAY

class UtilityCog(commands.Cog, name="Utilidad"):
    """Comandos de utilidad general, memoria y comandos dinámicos."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='guardar', help='Guarda un mensaje en la memoria.')
    async def guardar_chat(self, ctx, *, mensaje: str):
        # Usar la zona horaria configurada para consistencia
        try:
            tz_str = os.getenv('TIMEZONE', 'UTC')
            user_timezone = pytz.timezone(tz_str)
        except pytz.UnknownTimeZoneError:
            user_timezone = pytz.timezone('UTC')
            
        now = datetime.now(user_timezone)
        turno_key = get_turno_key()
        turno_display = TURNOS_DISPLAY.get(turno_key, "Desconocido")
        await db_execute("INSERT INTO chats_guardados (user_id, user_name, message, timestamp, turno) VALUES (%s, %s, %s, %s, %s)", (ctx.author.id, ctx.author.name, mensaje, now, turno_display))
        await ctx.send(f"✅ ¡Mensaje guardado! (Turno: {turno_display})")

    @commands.command(name='buscar', help='Busca en la memoria. Uso: !buscar <término/fecha>')
    async def buscar(self, ctx, *, query: str):
        sql_query, params, title = "", (), ""
        
        # Obtener la zona horaria para la consulta
        tz_str = os.getenv('TIMEZONE', 'UTC')
        
        try:
            search_date = datetime.strptime(query, '%Y-%m-%d').date()
            # Usamos AT TIME ZONE para asegurar que la comparación de fechas respete la zona horaria
            sql_query = f"SELECT * FROM chats_guardados WHERE DATE(timestamp AT TIME ZONE '{tz_str}') = %s ORDER BY timestamp ASC"
            params, title = (search_date,), f"Memoria del {search_date.strftime('%d-%m-%Y')}"
        except ValueError:
            clean_query = query.lower().strip()
            if clean_query == 'hoy':
                search_date = datetime.now(pytz.timezone(tz_str)).date()
                sql_query = f"SELECT * FROM chats_guardados WHERE DATE(timestamp AT TIME ZONE '{tz_str}') = %s ORDER BY timestamp ASC"
                params, title = (search_date,), f"Memoria de hoy ({search_date.strftime('%d-%m-%Y')})"
            elif clean_query == 'ayer':
                search_date = (datetime.now(pytz.timezone(tz_str)) - timedelta(days=1)).date()
                sql_query = f"SELECT * FROM chats_guardados WHERE DATE(timestamp AT TIME ZONE '{tz_str}') = %s ORDER BY timestamp ASC"
                params, title = (search_date,), f"Memoria de ayer ({search_date.strftime('%d-%m-%Y')})"
            else:
                sql_query, params, title = "SELECT * FROM chats_guardados WHERE LOWER(message) LIKE %s ORDER BY timestamp DESC", (f"%{query.lower()}%",), f"Resultados para: '{query}'"
        
        rows = await db_execute(sql_query, params, fetch='all')
        if not rows:
            await ctx.send(f"🤔 No encontré resultados para: **{query}**."); return
        
        description = ""
        for r in rows:
            # Convertir a la zona horaria local para mostrar
            local_ts = r['timestamp'].astimezone(pytz.timezone(tz_str))
            description += f"**- {local_ts.strftime('%H:%M')} por {r['user_name']}**: `{r['message']}`\n"
        embed = discord.Embed(title=title, color=discord.Color.green())
        if len(description) > 4000:
            description = description[:4000] + "\n\n*[Resultados truncados por su longitud]*"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name='resumir', help='Crea un resumen con IA de la memoria. Uso: !resumir <hoy/ayer/término>')
    async def resumir(self, ctx, *, query: str):
        sql_query, params, title_prefix = "", (), ""
        
        tz_str = os.getenv('TIMEZONE', 'UTC')

        try:
            search_date = datetime.strptime(query, '%Y-%m-%d').date()
            sql_query = f"SELECT user_name, message FROM chats_guardados WHERE DATE(timestamp AT TIME ZONE '{tz_str}') = %s ORDER BY timestamp ASC"
            params, title_prefix = (search_date,), f"Resumen del {search_date.strftime('%d-%m-%Y')}"
        except ValueError:
            clean_query = query.lower().strip()
            if clean_query == 'hoy':
                search_date = datetime.now(pytz.timezone(tz_str)).date()
                sql_query = f"SELECT user_name, message FROM chats_guardados WHERE DATE(timestamp AT TIME ZONE '{tz_str}') = %s ORDER BY timestamp ASC"
                params, title_prefix = (search_date,), f"Resumen de hoy ({search_date.strftime('%d-%m-%Y')})"
            elif clean_query == 'ayer':
                search_date = (datetime.now(pytz.timezone(tz_str)) - timedelta(days=1)).date()
                sql_query = f"SELECT user_name, message FROM chats_guardados WHERE DATE(timestamp AT TIME ZONE '{tz_str}') = %s ORDER BY timestamp ASC"
                params, title_prefix = (search_date,), f"Resumen de ayer ({search_date.strftime('%d-%m-%Y')})"
            else:
                sql_query, params, title_prefix = "SELECT user_name, message FROM chats_guardados WHERE LOWER(message) LIKE %s ORDER BY timestamp DESC", (f"%{query.lower()}%",), f"Resumen sobre '{query}'"

        async with ctx.typing():
            rows = await db_execute(sql_query, params, fetch='all')
            if not rows:
                await ctx.send(f"🤔 No encontré nada que resumir para: **{query}**."); return
            
            chat_log = "\n".join([f"{row['user_name']}: {row['message']}" for row in rows])
            if len(chat_log) > 15000: chat_log = chat_log[:15000]

            try:
                prompt_resumen = f"**TAREA:** Eres un asistente que resume conversaciones. Analiza el siguiente registro de chat y extrae los puntos, ideas o eventos más importantes. Presenta el resumen en una lista de viñetas (bullet points). Sé conciso y claro.\n\n**REGISTRO DE CHAT:**\n---\n{chat_log}\n---\n\n**RESUMEN:**"
                response = await self.bot.gemini_model.generate_content_async(prompt_resumen)
                embed = discord.Embed(title=f"🧠 {title_prefix}", color=discord.Color.blue())
                embed.description = response.text
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send("❌ Error al generar el resumen con la IA."); print(f"Error en !resumir: {e}")

    @commands.command(name='crearcomando', help='Crea un comando personalizado.')
    @commands.has_permissions(administrator=True)
    async def crear_comando(self, ctx, nombre: str, *, respuesta: str):
        await db_execute("INSERT INTO comandos_dinamicos (nombre_comando, respuesta_comando, creador_id, creador_nombre) VALUES (%s, %s, %s, %s) ON CONFLICT (nombre_comando) DO UPDATE SET respuesta_comando = EXCLUDED.respuesta_comando, creador_id = EXCLUDED.creador_id, creador_nombre = EXCLUDED.creador_nombre", (nombre.lower(), respuesta, ctx.author.id, ctx.author.name))
        self.bot.dynamic_commands[nombre.lower()] = respuesta 
        await ctx.send(f"✅ ¡Comando `!{nombre.lower()}` creado/actualizado!")

    @commands.command(name='borrarcomando', help='Borra un comando personalizado.')
    @commands.has_permissions(administrator=True)
    async def borrar_comando(self, ctx, nombre: str):
        nombre = nombre.lower()
        rows = await db_execute("DELETE FROM comandos_dinamicos WHERE nombre_comando = %s", (nombre,))
        if rows > 0:
            if nombre in self.bot.dynamic_commands: del self.bot.dynamic_commands[nombre]
            await ctx.send(f"✅ ¡Comando `!{nombre}` borrado!")
        else:
            await ctx.send(f"🤔 No encontré un comando personalizado llamado `{nombre}`.")

    @commands.command(name='saludar', help='Un simple saludo.')
    async def saludar(self, ctx):
        await ctx.send(f'¡Hola, {ctx.author.name}! Estoy listo para tus órdenes.')

async def setup(bot):
    await bot.add_cog(UtilityCog(bot))
