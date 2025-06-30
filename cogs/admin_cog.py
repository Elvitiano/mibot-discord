import discord
from discord.ext import commands
from datetime import datetime, date
import json
import io
import sqlite3
import asyncio
from unidecode import unidecode
from utils.db_manager import db_execute, get_db_connection

TABLES_TO_MIGRATE = [
    'personas', 'datos_persona', 'reglas_ia', 
    'comandos_config', 'permisos_comandos'
]

class AdminCog(commands.Cog, name="Administración"):
    """Comandos para la administración del bot y del servidor."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='privatizar', help='Hace que un comando sea de uso restringido.')
    @commands.has_permissions(administrator=True)
    async def privatizar(self, ctx, nombre_comando: str):
        cmd = self.bot.get_command(nombre_comando.lower())
        if not cmd or cmd.name in ['privatizar', 'publicar', 'permitir', 'denegar', 'estado_comandos']:
            await ctx.send(f"❌ No se puede privatizar `!{nombre_comando}`."); return
        await db_execute("INSERT INTO comandos_config (nombre_comando, estado) VALUES (%s, %s) ON CONFLICT (nombre_comando) DO UPDATE SET estado = EXCLUDED.estado", (cmd.name, 'privado'))
        await ctx.send(f"🔒 El comando `!{cmd.name}` ahora es privado.")

    @commands.command(name='publicar', help='Hace que un comando sea de uso público.')
    @commands.has_permissions(administrator=True)
    async def publicar(self, ctx, nombre_comando: str):
        cmd = self.bot.get_command(nombre_comando.lower())
        if not cmd: await ctx.send(f"❌ No existe el comando `!{nombre_comando}`."); return
        await db_execute("INSERT INTO comandos_config (nombre_comando, estado) VALUES (%s, %s) ON CONFLICT (nombre_comando) DO UPDATE SET estado = EXCLUDED.estado", (cmd.name, 'publico'))
        await ctx.send(f"🌍 El comando `!{cmd.name}` ahora es público.")

    @commands.command(name='permitir', help='Concede a un usuario permiso para usar un comando privado.')
    @commands.has_permissions(administrator=True)
    async def permitir(self, ctx, miembro: discord.Member, nombre_comando: str):
        cmd_name = nombre_comando.lower()
        if not self.bot.get_command(cmd_name): await ctx.send(f"❌ No existe el comando `!{cmd_name}`."); return
        await db_execute("INSERT INTO permisos_comandos (user_id, nombre_comando) VALUES (%s, %s) ON CONFLICT (user_id, nombre_comando) DO NOTHING", (miembro.id, cmd_name))
        await ctx.send(f"🔑 ¡Llave entregada! {miembro.mention} ahora puede usar `!{cmd_name}`.")

    @commands.command(name='denegar', help='Quita el permiso a un usuario para un comando.')
    @commands.has_permissions(administrator=True)
    async def denegar(self, ctx, miembro: discord.Member, nombre_comando: str):
        rows = await db_execute("DELETE FROM permisos_comandos WHERE user_id = %s AND nombre_comando = %s", (miembro.id, nombre_comando.lower()))
        if rows == 0: await ctx.send(f"🤔 {miembro.mention} no tenía permiso para `!{nombre_comando}`.")
        else: await ctx.send(f"✅ Acceso a `!{nombre_comando}` revocado para {miembro.mention}.")

    @commands.command(name='estado_comandos', help='Muestra el estado de los comandos.')
    @commands.has_permissions(administrator=True)
    async def estado_comandos(self, ctx):
        configs = await db_execute("SELECT nombre_comando, estado FROM comandos_config", fetch='all')
        configuraciones = {row['nombre_comando']: row['estado'] for row in configs} if configs else {}
        embed = discord.Embed(title="Estado de Permisos de Comandos", color=discord.Color.dark_grey())
        description = ""
        for cmd in sorted(self.bot.commands, key=lambda c: c.name):
            if cmd.hidden: continue
            estado_texto = configuraciones.get(cmd.name, 'publico')
            estado_emoji = 'Privado 🔒' if estado_texto == 'privado' else 'Público 🌍'
            description += f"**`!{cmd.name}`**: {estado_emoji}\n"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name='status', help='Realiza un chequeo de salud del bot y sus conexiones.')
    @commands.has_permissions(administrator=True)
    async def status(self, ctx):
        """Verifica el estado de las conexiones críticas del bot."""
        embed = discord.Embed(title="🩺 Chequeo de Salud del Bot 🩺", color=discord.Color.blue())
        
        # 1. Chequeo de la Base de Datos
        try:
            conn = get_db_connection()
            conn.close()
            embed.add_field(name="Base de Datos (Supabase)", value="✅ Conectada", inline=False)
        except Exception as e:
            embed.add_field(name="Base de Datos (Supabase)", value=f"❌ Falló: {e}", inline=False)

        # 2. Chequeo de Gemini AI
        try:
            await self.bot.gemini_model.count_tokens("test")
            embed.add_field(name="IA (Gemini)", value="✅ Conectada", inline=False)
        except Exception as e:
            embed.add_field(name="IA (Gemini)", value=f"❌ Falló: {e}", inline=False)

        # 3. Chequeo de ElevenLabs
        if self.bot.elevenlabs_client:
            try:
                await asyncio.to_thread(self.bot.elevenlabs_client.models.get_all)
                embed.add_field(name="Audio (ElevenLabs)", value="✅ Conectado", inline=False)
            except Exception as e:
                embed.add_field(name="Audio (ElevenLabs)", value=f"❌ Falló: {e}", inline=False)
        else:
            embed.add_field(name="Audio (ElevenLabs)", value="⚪ No configurado", inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name='anuncio', help='Envía un anuncio. Uso: !anuncio <#canal...|todos|categoria> <mensaje>')
    @commands.has_permissions(administrator=True)
    async def anuncio(self, ctx, *, args: str):
        if not args:
            await ctx.send("❌ Faltan argumentos. Uso: `!anuncio <#canal... | todos | categoria> <mensaje>`"); return

        parts = args.split()
        canales_destino = []
        mensaje_str = ""

        if ctx.message.channel_mentions:
            canales_destino = ctx.message.channel_mentions
            mensaje_str_reconstruido = args
            for mention in ctx.message.channel_mentions:
                mensaje_str_reconstruido = mensaje_str_reconstruido.replace(mention.mention, "").strip()
            mensaje_str = mensaje_str_reconstruido
        else:
            target = parts[0]
            if target.lower() == 'todos':
                canales_destino = [ch for ch in ctx.guild.text_channels if ch.permissions_for(ctx.guild.me).send_messages]
                mensaje_str = " ".join(parts[1:])
            else:
                categoria_encontrada = None
                mensaje_encontrado = ""
                sorted_categories = sorted(ctx.guild.categories, key=lambda c: len(c.name), reverse=True)
                for categoria in sorted_categories:
                    cat_name_normalized = unidecode(categoria.name).lower()
                    args_normalized = unidecode(args).lower()
                    if args_normalized.startswith(cat_name_normalized):
                        categoria_encontrada = categoria
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

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
