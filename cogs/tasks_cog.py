import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from utils.db_manager import db_execute

class TasksCog(commands.Cog, name="Tareas Programadas"):
    """Comandos para programar mensajes y tareas."""
    def __init__(self, bot):
        self.bot = bot
        self.check_scheduled_tasks.start()

    def cog_unload(self):
        self.check_scheduled_tasks.cancel()

    @tasks.loop(seconds=60)
    async def check_scheduled_tasks(self):
        now = datetime.now()
        tasks_to_run = await db_execute("SELECT id, channel_id, message_content FROM tareas_programadas WHERE send_at <= ? AND sent = 0", (now,), fetch='all')
        for task_id, channel_id, message_content in tasks_to_run:
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(message_content)
                    await db_execute("UPDATE tareas_programadas SET sent = 1 WHERE id = ?", (task_id,))
                except Exception as e:
                    print(f"Error al enviar tarea programada {task_id}: {e}")
                    await db_execute("UPDATE tareas_programadas SET sent = 2 WHERE id = ?", (task_id,))
            else:
                print(f"No se pudo encontrar el canal {channel_id} para la tarea {task_id}. Marcada como fallida.")
                await db_execute("UPDATE tareas_programadas SET sent = 2 WHERE id = ?", (task_id,))

    @check_scheduled_tasks.before_loop
    async def before_check_scheduled_tasks(self):
        await self.bot.wait_until_ready()

    @commands.command(name='programar', help='Programa un mensaje. Uso: !programar <#canal> "AAAA-MM-DD HH:MM" <mensaje>')
    @commands.has_permissions(administrator=True)
    async def programar(self, ctx, canal: discord.TextChannel, fecha_hora_str: str, *, mensaje: str):
        try:
            send_time = datetime.strptime(fecha_hora_str, '%Y-%m-%d %H:%M')
        except ValueError:
            await ctx.send("❌ Formato de fecha y hora incorrecto. Usa `AAAA-MM-DD HH:MM`."); return
        if send_time <= datetime.now():
            await ctx.send("❌ La fecha y hora deben ser en el futuro."); return
        await db_execute("INSERT INTO tareas_programadas (guild_id, channel_id, author_id, message_content, send_at) VALUES (?, ?, ?, ?, ?)", (ctx.guild.id, canal.id, ctx.author.id, mensaje, send_time))
        last_task = await db_execute("SELECT id FROM tareas_programadas ORDER BY id DESC LIMIT 1", fetch='one')
        task_id = last_task[0] if last_task else 'desconocido'
        await ctx.send(f"✅ ¡Mensaje programado! Se enviará en {canal.mention} el `{send_time.strftime('%Y-%m-%d a las %H:%M')}`. **ID de tarea: {task_id}**")

    @commands.command(name='programar-serie', help='Genera y programa una serie de posts. Uso: !programar-serie <#canal> <cantidad> "AAAA-MM-DD HH:MM" <tema>')
    @commands.has_permissions(administrator=True)
    async def programar_serie(self, ctx, canal: discord.TextChannel, cantidad: int, fecha_hora_inicio_str: str, *, tema: str):
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
                prompt_serie = f'**TAREA:** Eres un creador de contenido experto. Genera una serie de {cantidad} publicaciones cortas y atractivas sobre el tema "{tema}".\n**REGLAS CRÍTICAS DE FORMATO:**\n1. Cada publicación debe ser un texto completo y coherente por sí mismo.\n2. Separa CADA publicación con el delimitador exacto y único: `|||---|||`\n3. No añadas números de lista (como 1., 2.) ni ningún otro texto introductorio o de cierre. Solo las publicaciones y el delimitador.'
                response = await self.bot.gemini_model.generate_content_async(prompt_serie)
                posts = response.text.split('|||---|||')
                if len(posts) < cantidad:
                    await ctx.send(f"⚠️ La IA generó menos posts de los solicitados ({len(posts)} de {cantidad}). Inténtalo de nuevo."); return
                created_tasks_ids = []
                for i, post_content in enumerate(posts[:cantidad]):
                    send_time = start_time + timedelta(days=i)
                    await db_execute("INSERT INTO tareas_programadas (guild_id, channel_id, author_id, message_content, send_at) VALUES (?, ?, ?, ?, ?)", (ctx.guild.id, canal.id, ctx.author.id, post_content.strip(), send_time))
                    last_task = await db_execute("SELECT id FROM tareas_programadas ORDER BY id DESC LIMIT 1", fetch='one')
                    if last_task: created_tasks_ids.append(str(last_task[0]))
                await ctx.send(f"✅ ¡Serie de {len(created_tasks_ids)} posts generada y programada en {canal.mention}! IDs de tarea: `{', '.join(created_tasks_ids)}`")
            except Exception as e:
                await ctx.send("❌ Error al generar la serie de contenido con la IA."); print(f"Error en !programar-serie: {e}")

    @commands.command(name='programar-ia', aliases=['programaria'], help='Genera y programa contenido con IA. Uso: !programar-ia <#canal> "AAAA-MM-DD HH:MM" <prompt>')
    @commands.has_permissions(administrator=True)
    async def programar_ia(self, ctx, canal: discord.TextChannel, fecha_hora_str: str, *, prompt: str):
        try:
            send_time = datetime.strptime(fecha_hora_str, '%Y-%m-%d %H:%M')
        except ValueError:
            await ctx.send("❌ Formato de fecha y hora incorrecto. Usa `AAAA-MM-DD HH:MM`."); return
        if send_time <= datetime.now():
            await ctx.send("❌ La fecha y hora deben ser en el futuro."); return
        await ctx.send(f"🧠 Entendido. Generando y programando contenido con IA...")
        async with ctx.typing():
            try:
                response = await self.bot.gemini_model.generate_content_async(prompt)
                mensaje_generado = response.text
                await db_execute("INSERT INTO tareas_programadas (guild_id, channel_id, author_id, message_content, send_at) VALUES (?, ?, ?, ?, ?)", (ctx.guild.id, canal.id, ctx.author.id, mensaje_generado, send_time))
                last_task = await db_execute("SELECT id FROM tareas_programadas ORDER BY id DESC LIMIT 1", fetch='one')
                task_id = last_task[0] if last_task else 'desconocido'
                await ctx.send(f"✅ ¡Contenido generado y programado! Se enviará en {canal.mention} el `{send_time.strftime('%Y-%m-%d a las %H:%M')}`. **ID de tarea: {task_id}**")
            except Exception as e:
                await ctx.send("❌ Error al generar o programar el contenido con la IA."); print(f"Error en !programar-ia: {e}")

    @commands.command(name='tareas', help='Muestra los mensajes programados pendientes.')
    @commands.has_permissions(administrator=True)
    async def tareas(self, ctx):
        pending_tasks = await db_execute("SELECT id, channel_id, author_id, send_at, message_content FROM tareas_programadas WHERE sent = 0 AND guild_id = ? ORDER BY send_at ASC", (ctx.guild.id,), fetch='all')
        if not pending_tasks:
            await ctx.send("No hay tareas programadas pendientes."); return
        embed = discord.Embed(title="🗓️ Tareas Programadas Pendientes", color=discord.Color.gold())
        description = ""
        for task_id, channel_id, author_id, send_at_str, message in pending_tasks:
            channel = self.bot.get_channel(channel_id)
            author = self.bot.get_user(author_id)
            channel_mention = channel.mention if channel else f"ID: {channel_id}"
            author_name = author.name if author else f"ID: {author_id}"
            send_at = datetime.fromisoformat(send_at_str)
            description += f"**ID: {task_id}** | {channel_mention} | Por: `{author_name}` | `{send_at.strftime('%Y-%m-%d %H:%M')}`\n```{message[:100]}{'...' if len(message) > 100 else ''}```\n"
        if len(description) > 4000:
            description = description[:4000] + "\n\n*[Resultados truncados]*"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name='borrartarea', help='Borra una tarea programada por su ID.')
    @commands.has_permissions(administrator=True)
    async def borrartarea(self, ctx, task_id: int):
        rows = await db_execute("DELETE FROM tareas_programadas WHERE id = ? AND guild_id = ?", (task_id, ctx.guild.id))
        if rows > 0:
            await ctx.send(f"✅ Tarea con ID `{task_id}` eliminada.")
        else:
            await ctx.send(f"🤔 No encontré una tarea pendiente con el ID `{task_id}` en este servidor.")

async def setup(bot):
    await bot.add_cog(TasksCog(bot))
