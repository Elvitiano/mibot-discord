import discord
from discord.ext import commands
from datetime import datetime, timedelta, date
import os
import sqlite3
import asyncio
from utils.db_manager import db_execute
from utils.helpers import get_turno_key, TURNOS_DISPLAY, parse_periodo

class OperatorCog(commands.Cog, name="Operadores y Estadísticas"):
    """Comandos para la gestión de operadores, LMs y estadísticas."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='apodo', help='Asigna un apodo a un usuario para un turno. Uso: !apodo <miembro> <dia|tarde|noche> <apodo>')
    @commands.has_permissions(administrator=True)
    async def apodo(self, ctx, miembro: discord.Member, turno: str, *, apodo_texto: str):
        turno = turno.lower()
        if turno not in ['dia', 'tarde', 'noche']:
            await ctx.send("❌ Turno inválido. Usa `dia`, `tarde` o `noche`."); return
        await db_execute(f"INSERT OR IGNORE INTO apodos_operador (user_id) VALUES (?)", (miembro.id,))
        await db_execute(f"UPDATE apodos_operador SET apodo_{turno} = ? WHERE user_id = ?", (apodo_texto, miembro.id))
        await ctx.send(f"✅ Apodo de {miembro.mention} para el turno de **{turno}** establecido como `{apodo_texto}`.")

    @commands.command(name='verapodo', help='Muestra los apodos de un usuario.')
    @commands.has_permissions(administrator=True)
    async def verapodo(self, ctx, miembro: discord.Member):
        apodos = await db_execute("SELECT apodo_dia, apodo_tarde, apodo_noche FROM apodos_operador WHERE user_id = ?", (miembro.id,), fetch='one')
        embed = discord.Embed(title=f"Apodos de {miembro.name}", color=discord.Color.purple())
        if apodos:
            embed.add_field(name="Día ☀️", value=f"`{apodos[0]}`" if apodos[0] else "No asignado", inline=True)
            embed.add_field(name="Tarde 🌅", value=f"`{apodos[1]}`" if apodos[1] else "No asignado", inline=True)
            embed.add_field(name="Noche 🌑", value=f"`{apodos[2]}`" if apodos[2] else "No asignado", inline=True)
        else:
            embed.description = "Este usuario no tiene apodos asignados."
        await ctx.send(embed=embed)

    @commands.command(name='quitarapodo', help='Elimina el apodo de un usuario para un turno. Uso: !quitarapodo <miembro> <dia|tarde|noche>')
    @commands.has_permissions(administrator=True)
    async def quitarapodo(self, ctx, miembro: discord.Member, turno: str):
        turno = turno.lower()
        if turno not in ['dia', 'tarde', 'noche']:
            await ctx.send("❌ Turno inválido. Usa `dia`, `tarde` o `noche`."); return
        rows = await db_execute(f"UPDATE apodos_operador SET apodo_{turno} = NULL WHERE user_id = ? AND apodo_{turno} IS NOT NULL", (miembro.id,))
        if rows > 0:
            await ctx.send(f"✅ Apodo de {miembro.mention} para el turno de **{turno}** eliminado.")
        else:
            await ctx.send(f"🤔 {miembro.mention} no tenía un apodo asignado para ese turno.")

    @commands.command(name='listaapodos', help='Muestra una lista de todos los apodos asignados.')
    @commands.has_permissions(administrator=True)
    async def listaapodos(self, ctx):
        todos_los_apodos = await db_execute("SELECT user_id, apodo_dia, apodo_tarde, apodo_noche FROM apodos_operador", fetch='all')
        if not todos_los_apodos:
            await ctx.send("No hay apodos asignados a ningún operador."); return
        embed = discord.Embed(title="📋 Lista de Apodos de Operadores", color=discord.Color.purple())
        description = ""
        for user_id, apodo_dia, apodo_tarde, apodo_noche in todos_los_apodos:
            if not any([apodo_dia, apodo_tarde, apodo_noche]): continue
            miembro = ctx.guild.get_member(user_id)
            nombre_operador = miembro.mention if miembro else f"ID: {user_id}"
            dia_str = f"`{apodo_dia}`" if apodo_dia else "N/A"
            tarde_str = f"`{apodo_tarde}`" if apodo_tarde else "N/A"
            noche_str = f"`{apodo_noche}`" if apodo_noche else "N/A"
            description += f"**{nombre_operador}**\n☀️ **Día:** {dia_str} | 🌅 **Tarde:** {tarde_str} | 🌑 **Noche:** {noche_str}\n\n"
        if not description:
            await ctx.send("No hay apodos asignados a ningún operador."); return
        if len(description) > 4000:
            description = description[:4000] + "\n\n*[Resultados truncados]*"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name='asignar', help='Asigna perfiles a operadores. Uso: !asignar <@op1> <perfil1> [@op2 <perfil2>...]')
    @commands.has_permissions(administrator=True)
    async def asignar(self, ctx, *, args: str):
        parts = args.split()
        if len(parts) < 2 or len(parts) % 2 != 0:
            await ctx.send("❌ Formato incorrecto. Usa: `!asignar <@op1> <perfil1> [@op2 <perfil2>...]`"); return
        pares = []
        for i in range(0, len(parts), 2):
            pares.append((parts[i], parts[i+1].lower()))
        perfiles_a_verificar = list(set([p[1] for p in pares]))
        placeholders = ','.join('?' for _ in perfiles_a_verificar)
        perfiles_existentes_rows = await db_execute(f"SELECT nombre FROM personas WHERE nombre IN ({placeholders})", tuple(perfiles_a_verificar), fetch='all')
        nombres_perfiles_existentes = {row[0] for row in perfiles_existentes_rows}
        perfiles_no_encontrados = [p for p in perfiles_a_verificar if p not in nombres_perfiles_existentes]
        if perfiles_no_encontrados:
            await ctx.send(f"❌ Los siguientes perfiles no existen: `{', '.join(perfiles_no_encontrados)}`. Créalos primero con `!crearperfil`."); return
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

    @commands.command(name='desasignar', help='Quita perfiles a operadores. Uso: !desasignar <@op1> <perfil1> [@op2 <perfil2>...]')
    @commands.has_permissions(administrator=True)
    async def desasignar(self, ctx, *, args: str):
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

    @commands.command(name='sincronizar-perfiles', help='Asigna TODOS los perfiles a TODOS los operadores del servidor.')
    @commands.has_permissions(administrator=True)
    async def sincronizar_perfiles(self, ctx):
        await ctx.send("⏳ Iniciando sincronización masiva... Esto puede tardar un momento.")
        async with ctx.typing():
            perfiles_rows = await db_execute("SELECT nombre FROM personas", fetch='all')
            if not perfiles_rows:
                await ctx.send("❌ No hay perfiles creados para asignar."); return
            perfiles_lista = [row[0] for row in perfiles_rows]
            operadores = [m for m in ctx.guild.members if not m.bot]
            if not operadores:
                await ctx.send("❌ No se encontraron operadores en el servidor."); return
            nuevas_asignaciones = 0
            for operador in operadores:
                for perfil in perfiles_lista:
                    rows_affected = await db_execute("INSERT OR IGNORE INTO operador_perfil (user_id, nombre_perfil) VALUES (?, ?)", (operador.id, perfil))
                    if rows_affected > 0:
                        nuevas_asignaciones += 1
        await ctx.send(f"✅ Sincronización completada. Se realizaron **{nuevas_asignaciones}** nuevas asignaciones a **{len(operadores)}** operadores.")

    @commands.command(name='desincronizar-perfiles', help='(PELIGRO) Elimina TODAS las asignaciones de perfiles.')
    @commands.has_permissions(administrator=True)
    async def desincronizar_perfiles(self, ctx):
        embed = discord.Embed(title="⚠️ ADVERTENCIA DE SEGURIDAD ⚠️", description="Estás a punto de **eliminar TODAS las asignaciones de perfiles** para TODOS los operadores. Esta acción no se puede deshacer.\n\nReacciona con ✅ para confirmar en los próximos 30 segundos.", color=discord.Color.red())
        confirm_msg = await ctx.send(embed=embed)
        await confirm_msg.add_reaction("✅"); await confirm_msg.add_reaction("❌")
        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id
        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            if str(reaction.emoji) == "✅":
                await confirm_msg.edit(content="⏳ Procediendo con la desincronización masiva...", embed=None, view=None)
                rows_deleted = await db_execute("DELETE FROM operador_perfil")
                await confirm_msg.edit(content=f"✅ Desincronización completada. Se eliminaron **{rows_deleted}** asignaciones de perfiles.")
            else:
                await confirm_msg.edit(content="❌ Operación cancelada.", embed=None, view=None)
        except asyncio.TimeoutError:
            await confirm_msg.edit(content="❌ Tiempo de espera agotado. Operación cancelada.", embed=None, view=None)

    @commands.command(name='misperfiles', help='Muestra los perfiles asignados. Uso: !misperfiles [miembro]')
    async def misperfiles(self, ctx, miembro: discord.Member = None):
        target_user = miembro or ctx.author
        perfiles = await db_execute("SELECT nombre_perfil FROM operador_perfil WHERE user_id = ? ORDER BY nombre_perfil ASC", (target_user.id,), fetch='all')
        if perfiles:
            lista_perfiles = "\n".join([f"- `{p[0]}`" for p in perfiles])
            embed = discord.Embed(title=f"Perfiles de {target_user.name}", description=lista_perfiles, color=discord.Color.blue())
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"🤔 {target_user.name} no tiene perfiles asignados.")

    @commands.command(name='lm', help='Formatea y envía un LM. Uso: !lm <perfil> <mensaje>')
    async def lm(self, ctx, nombre_perfil: str, *, mensaje: str):
        nombre_perfil = nombre_perfil.lower()
        asignacion = await db_execute("SELECT 1 FROM operador_perfil WHERE user_id = ? AND nombre_perfil = ?", (ctx.author.id, nombre_perfil), fetch='one')
        if not asignacion:
            await ctx.send(f"❌ No tienes asignado el perfil `{nombre_perfil}`. Usa `!misperfiles` para ver tus perfiles."); return
        today_str, turno_key = date.today().isoformat(), get_turno_key()
        count_row = await db_execute("SELECT COUNT(*) FROM lm_logs WHERE DATE(timestamp) = ? AND turno = ?", (today_str, turno_key), fetch='one')
        cambio_num = count_row[0] + 1
        await db_execute("INSERT INTO lm_logs (user_id, perfil_usado, message_content, timestamp, turno) VALUES (?, ?, ?, ?, ?)", (ctx.author.id, nombre_perfil, mensaje, datetime.now(), turno_key))
        now = datetime.now()
        h1_dt, h2_dt = now, now + timedelta(hours=1)
        h1_str = h1_dt.strftime('%#I' if os.name != 'nt' else '%I').lstrip('0') + h1_dt.strftime('%p').lower()
        h2_str = h2_dt.strftime('%#I' if os.name != 'nt' else '%I').lstrip('0') + h2_dt.strftime('%p').lower()
        time_range = f"{h1_str} - {h2_str}"
        apodo_row = await db_execute(f"SELECT apodo_{turno_key} FROM apodos_operador WHERE user_id = ?", (ctx.author.id,), fetch='one')
        operador_name = apodo_row[0] if apodo_row and apodo_row[0] else ctx.author.name
        perfil_operador_str = f"{nombre_perfil.title()}/ {operador_name}"
        mensaje_final = f"Cambio# {cambio_num} ({TURNOS_DISPLAY.get(turno_key)})   {time_range}\n{perfil_operador_str}\n\n😎 {mensaje}"
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
            "INSERT INTO exitos_logs (author_id, log_message, timestamp) VALUES (?, ?, ?)",
            (ctx.author.id, log_message, datetime.now())
        )
        await ctx.message.add_reaction('🎉')
        await ctx.send(f"¡Éxito registrado!\n```{log_message}```", delete_after=20)

    # --- MÓDULO DE ESTADÍSTICAS ---
    @commands.command(name='estadisticas', aliases=['stats'], help='Muestra estadísticas de LM. Uso: !stats [periodo] [filtro]')
    @commands.has_permissions(administrator=True)
    async def estadisticas(self, ctx, periodo: str = 'hoy', *, filtro: str = None):
        where_clauses, params, title_periodo = parse_periodo(periodo)
        if not where_clauses:
            await ctx.send(f"❌ {title_periodo}"); return
        
        title = f"Estadísticas {title_periodo}"

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
        
        embed = discord.Embed(title=f"📊 {title}", color=discord.Color.green())
        if not results:
            embed.description = "No se encontraron registros para los criterios seleccionados."
            await ctx.send(embed=embed); return

        total_lms = sum(count for _, _, count in results)
        embed.description = f"**Total de LMs:** {total_lms}\n\n**Desglose por Operador y Turno:**"
        stats_by_user = {}
        for user_id, turno, count in results:
            if user_id not in stats_by_user: stats_by_user[user_id] = {'total': 0, 'turnos': {}}
            stats_by_user[user_id]['total'] += count
            stats_by_user[user_id]['turnos'][turno] = count
        
        sorted_users = sorted(stats_by_user.items(), key=lambda item: item[1]['total'], reverse=True)
        description_body = ""
        for user_id, data in sorted_users:
            miembro = ctx.guild.get_member(user_id)
            nombre_operador = miembro.mention if miembro else f"ID: {user_id}"
            turnos_str_parts = [f"☀️ {data['turnos']['dia']}" if 'dia' in data['turnos'] else "", f"🌅 {data['turnos']['tarde']}" if 'tarde' in data['turnos'] else "", f"🌑 {data['turnos']['noche']}" if 'noche' in data['turnos'] else ""]
            turnos_str = ' | '.join(filter(None, turnos_str_parts))
            description_body += f"**{nombre_operador}**: {data['total']} LMs en total ({turnos_str})\n"
        
        embed.description += "\n" + description_body
        await ctx.send(embed=embed)

    @commands.command(name='verexitos', help='Muestra los logs de éxito. Uso: !verexitos [periodo] [filtro]')
    @commands.has_permissions(administrator=True)
    async def verexitos(self, ctx, periodo: str = 'hoy', *, filtro: str = None):
        where_clauses, params, title_periodo = parse_periodo(periodo)
        if not where_clauses:
            await ctx.send(f"❌ {title_periodo}"); return
            
        title = f"Registro de Éxitos {title_periodo}"

        if filtro:
            where_clauses.append("log_message LIKE ?")
            params.append(f"%{filtro}%")
            title += f" (Filtro: {filtro})"

        query = f"SELECT author_id, log_message, timestamp FROM exitos_logs WHERE {' AND '.join(where_clauses)} ORDER BY timestamp DESC"
        results = await db_execute(query, tuple(params), fetch='all')

        embed = discord.Embed(title=f"🏆 {title}", color=discord.Color.gold())
        if not results:
            embed.description = "No se encontraron registros de éxitos para los criterios seleccionados."
            await ctx.send(embed=embed); return

        description = ""
        for author_id, log_message, ts in results:
            author = ctx.guild.get_member(author_id)
            author_name = author.mention if author else f"ID: {author_id}"
            
            log_entry = (
                f"**[{ts.strftime('%d/%m %H:%M')}] - Registrado por: {author_name}**\n"
                f"> {log_message}\n\n"
            )
            
            
            if len(description) + len(log_entry) > 4000:
                description += "*[Resultados truncados por su longitud]*"; break
            description += log_entry
            
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name='registrolm', aliases=['verlms'], help='Muestra los LMs enviados. Uso: !registrolm [periodo] [filtro]')
    @commands.has_permissions(administrator=True)
    async def registrolm(self, ctx, periodo: str = 'hoy', *, filtro: str = None):
        where_clauses, params, title_periodo = parse_periodo(periodo)
        if not where_clauses:
            await ctx.send(f"❌ {title_periodo}"); return
            
        title = f"Registro de LMs {title_periodo}"

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

        query = f"SELECT user_id, perfil_usado, message_content, timestamp FROM lm_logs WHERE {' AND '.join(where_clauses)} ORDER BY timestamp DESC"
        results = await db_execute(query, tuple(params), fetch='all')

        embed = discord.Embed(title=f"📜 {title}", color=discord.Color.orange())
        if not results:
            embed.description = "No se encontraron LMs para los criterios seleccionados."
            await ctx.send(embed=embed); return

        description = ""
        for user_id, perfil, mensaje, ts_str in results:
            ts = datetime.fromisoformat(ts_str)
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

async def setup(bot):
    await bot.add_cog(OperatorCog(bot))
