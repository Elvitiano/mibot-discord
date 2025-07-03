import discord
from discord.ext import commands
from datetime import datetime, timedelta
import os
import pytz
from utils.db_manager import db_execute
from utils.helpers import get_turno_key, TURNOS_DISPLAY

class LoggingCog(commands.Cog, name="Registro de Actividad"):
    """Comandos para registrar LMs y éxitos."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='lm', help='Formatea y envía un LM. Uso: !lm [perfil] <mensaje>')
    async def lm(self, ctx, *, args: str):
        if not args:
            await ctx.send("❌ Debes escribir un mensaje.", delete_after=10)
            return

        parts = args.split(maxsplit=1)
        possible_profile = parts[0].lower()
        
        nombre_perfil = None
        mensaje = args

        asignacion = await db_execute("SELECT 1 FROM operador_perfil WHERE user_id = %s AND nombre_perfil = %s", (ctx.author.id, possible_profile), fetch='one')
        
        if asignacion:
            if len(parts) > 1:
                nombre_perfil = possible_profile
                mensaje = parts[1]
            else:
                await ctx.send(f"❌ Escribiste el perfil `{possible_profile}` pero olvidaste el mensaje.", delete_after=10)
                return
        
        turno_key = get_turno_key()
        
        try:
            tz_str = os.getenv('TIMEZONE', 'UTC')
            user_timezone = pytz.timezone(tz_str)
        except pytz.UnknownTimeZoneError:
            await ctx.send(f"⚠️ Zona horaria '{tz_str}' no reconocida. Usando UTC por defecto.", delete_after=15)
            user_timezone = pytz.timezone('UTC')
            
        now = datetime.now(user_timezone)
        today_str = now.date().isoformat()

        count_row = await db_execute("SELECT COUNT(*) FROM lm_logs WHERE DATE(timestamp AT TIME ZONE %s) = %s AND turno = %s", (tz_str, today_str, turno_key), fetch='one')
        cambio_num = count_row['count'] + 1
        
        perfil_a_loguear = nombre_perfil if nombre_perfil else 'N/A'
        await db_execute("INSERT INTO lm_logs (user_id, perfil_usado, message_content, timestamp, turno) VALUES (%s, %s, %s, %s, %s)", (ctx.author.id, perfil_a_loguear, mensaje, now, turno_key))

        h1_dt = now
        h2_dt = now + timedelta(hours=1)
        h1_str = h1_dt.strftime('%I:%M %p').lstrip('0').lower()
        h2_str = h2_dt.strftime('%I:%M %p').lstrip('0').lower()
        time_range = f"{h1_str} - {h2_str}"

        header = f"Cambio# {cambio_num} ({TURNOS_DISPLAY.get(turno_key)})   {time_range}"
        
        info_line = ""
        if nombre_perfil:
            apodo_row = await db_execute(f"SELECT apodo_{turno_key} FROM apodos_operador WHERE user_id = %s", (ctx.author.id,), fetch='one')
            operador_name = apodo_row[f'apodo_{turno_key}'] if apodo_row and apodo_row[f'apodo_{turno_key}'] else ctx.author.name
            info_line = f"{nombre_perfil.title()}/ {operador_name}"

        if info_line:
            mensaje_final = f"{header}\n{info_line}\n\n😎 {mensaje}"
        else:
            mensaje_final = f"{header}\n\n😎 {mensaje}"
        
        try:
            await ctx.message.delete()
            await ctx.send(mensaje_final)
        except discord.Forbidden:
            await ctx.send("⚠️ No tengo permisos para borrar tu comando, pero aquí está tu LM:", delete_after=10)
            await ctx.send(mensaje_final)
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error inesperado al enviar el LM. Error: {e}")

    @commands.command(name='exito', help='Registra un log de éxito. Uso: !exito <texto del log>')
    async def exito(self, ctx, *, log_message: str):
        """Registra una interacción exitosa en la base de datos."""
        await db_execute(
            "INSERT INTO exitos_logs (author_id, log_message, timestamp) VALUES (%s, %s, %s)",
            (ctx.author.id, log_message, datetime.now(pytz.utc))
        )
        await ctx.message.add_reaction('🎉')
        await ctx.send(f"¡Éxito registrado!\n```{log_message}```", delete_after=20)

async def setup(bot):
    await bot.add_cog(LoggingCog(bot))
