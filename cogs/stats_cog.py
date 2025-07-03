import discord
from discord.ext import commands
from datetime import datetime
from utils.db_manager import db_execute
from utils.helpers import parse_periodo

class StatsCog(commands.Cog, name="Estadísticas"):
    """Comandos para visualizar estadísticas y registros."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='estadisticas', aliases=['stats'], help='Muestra estadísticas de LM. Uso: !stats [periodo] [filtro]')
    @commands.has_permissions(administrator=True)
    async def estadisticas(self, ctx, periodo: str = 'hoy', *, filtro: str = None):
        where_clauses, params, title_periodo = parse_periodo(periodo)
        if not where_clauses:
            await ctx.send(f"❌ {title_periodo}"); return
        
        title = f"Estadísticas {title_periodo}"

        if filtro:
            filtro_lower = filtro.lower()
            if filtro_lower in ['dia', 'tarde', 'noche']:
                where_clauses.append("turno = %s")
                params.append(filtro_lower)
                title += f" (Turno: {filtro_lower.title()})"
            else:
                try:
                    miembro = await commands.MemberConverter().convert(ctx, filtro)
                    where_clauses.append("user_id = %s")
                    params.append(miembro.id)
                    title += f" (Operador: {miembro.display_name})"
                except commands.MemberNotFound:
                    user_ids_rows = await db_execute("SELECT user_id FROM apodos_operador WHERE apodo_dia LIKE %s OR apodo_tarde LIKE %s OR apodo_noche LIKE %s", (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'), fetch='all')
                    if user_ids_rows:
                        ids = [row['user_id'] for row in user_ids_rows]
                        placeholders = ','.join('%s' for _ in ids)
                        where_clauses.append(f"user_id IN ({placeholders})")
                        params.extend(ids)
                        title += f" (Apodo: {filtro})"
                    else:
                        await ctx.send(f"🤔 No encontré ningún operador con la mención o apodo `{filtro}`."); return

        query = f"SELECT user_id, turno, COUNT(*) as count FROM lm_logs WHERE {' AND '.join(where_clauses)} GROUP BY user_id, turno ORDER BY COUNT(*) DESC"
        results = await db_execute(query, tuple(params), fetch='all')
        
        embed = discord.Embed(title=f"📊 {title}", color=discord.Color.green())
        if not results:
            embed.description = "No se encontraron registros para los criterios seleccionados."
            await ctx.send(embed=embed); return

        total_lms = sum(row['count'] for row in results)
        embed.description = f"**Total de LMs:** {total_lms}\n\n**Desglose por Operador y Turno:**"
        stats_by_user = {}
        for row in results:
            user_id, turno, count = row['user_id'], row['turno'], row['count']
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
            where_clauses.append("log_message LIKE %s")
            params.append(f"%%{filtro}%%")
            title += f" (Filtro: {filtro})"

        query = f"SELECT author_id, log_message, timestamp FROM exitos_logs WHERE {' AND '.join(where_clauses)} ORDER BY timestamp DESC"
        results = await db_execute(query, tuple(params), fetch='all')

        embed = discord.Embed(title=f"🏆 {title}", color=discord.Color.gold())
        if not results:
            embed.description = "No se encontraron registros de éxitos para los criterios seleccionados."
            await ctx.send(embed=embed); return

        description = ""
        for row in results:
            author = ctx.guild.get_member(row['author_id'])
            author_name = author.mention if author else f"ID: {row['author_id']}"
            ts = row['timestamp']
            
            log_entry = (
                f"**[{ts.strftime('%d/%m %H:%M')}] - Registrado por: {author_name}**\n"
                f"> {row['log_message']}\n\n"
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
                where_clauses.append("turno = %s")
                params.append(filtro_lower)
                title += f" (Turno: {filtro_lower.title()})"
            else:
                try:
                    miembro = await commands.MemberConverter().convert(ctx, filtro)
                    where_clauses.append("user_id = %s")
                    params.append(miembro.id)
                    title += f" (Operador: {miembro.display_name})"
                except commands.MemberNotFound:
                    user_ids_rows = await db_execute("SELECT user_id FROM apodos_operador WHERE apodo_dia LIKE %s OR apodo_tarde LIKE %s OR apodo_noche LIKE %s", (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'), fetch='all')
                    if user_ids_rows:
                        ids = [row['user_id'] for row in user_ids_rows]
                        placeholders = ','.join('%s' for _ in ids)
                        where_clauses.append(f"user_id IN ({placeholders})")
                        params.extend(ids)
                        title += f" (Apodo: {filtro})"
                    else:
                        await ctx.send(f"🤔 No encontré ningún operador con la mención o apodo `{filtro}`."); return

        query = f"SELECT user_id, perfil_usado, message_content, timestamp, turno FROM lm_logs WHERE {' AND '.join(where_clauses)} ORDER BY timestamp DESC"
        results = await db_execute(query, tuple(params), fetch='all')

        embed = discord.Embed(title=f"📜 {title}", color=discord.Color.orange())
        if not results:
            embed.description = "No se encontraron LMs para los criterios seleccionados."
            await ctx.send(embed=embed); return

        all_apodos_rows = await db_execute("SELECT user_id, apodo_dia, apodo_tarde, apodo_noche FROM apodos_operador", fetch='all')
        apodos_map = {row['user_id']: row for row in all_apodos_rows}

        description = ""
        for row in results:
            ts = row['timestamp']
            miembro = ctx.guild.get_member(row['user_id'])
            
            operador_name = miembro.mention if miembro else f"ID: {row['user_id']}"
            turno_log = row['turno']
            user_apodos = apodos_map.get(row['user_id'])
            if user_apodos and user_apodos.get(f'apodo_{turno_log}'):
                operador_name = user_apodos[f'apodo_{turno_log}']

            perfil_str = f"Perfil: `{row['perfil_usado']}` | " if row['perfil_usado'] != 'N/A' else ""
            
            log_entry = (
                f"**[{ts.strftime('%H:%M')}] - {perfil_str}Op: {operador_name}**\n"
                f"> {row['message_content']}\n\n"
            )
            
            if len(description) + len(log_entry) > 4000:
                description += "*[Resultados truncados por su longitud]*"
                break
            description += log_entry
            
        embed.description = description
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(StatsCog(bot))
