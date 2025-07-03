import discord
from discord.ext import commands
import psycopg2
import asyncio
from utils.db_manager import db_execute

class ProfileCog(commands.Cog, name="Gestión de Operadores"):
    """Comandos para la gestión de apodos y perfiles de operadores."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='apodo', help='Asigna un apodo a un usuario para un turno. Uso: !apodo <miembro> <dia|tarde|noche> <apodo>')
    @commands.has_permissions(administrator=True)
    async def apodo(self, ctx, miembro: discord.Member, turno: str, *, apodo_texto: str):
        turno = turno.lower()
        if turno not in ['dia', 'tarde', 'noche']:
            await ctx.send("❌ Turno inválido. Usa `dia`, `tarde` o `noche`."); return
        
        query = f"""
            INSERT INTO apodos_operador (user_id, apodo_{turno}) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET apodo_{turno} = EXCLUDED.apodo_{turno};
        """
        await db_execute(query, (miembro.id, apodo_texto))
        await ctx.send(f"✅ Apodo de {miembro.mention} para el turno de **{turno}** establecido como `{apodo_texto}`.")

    @commands.command(name='verapodo', help='Muestra los apodos de un usuario.')
    @commands.has_permissions(administrator=True)
    async def verapodo(self, ctx, miembro: discord.Member):
        apodos = await db_execute("SELECT apodo_dia, apodo_tarde, apodo_noche FROM apodos_operador WHERE user_id = %s", (miembro.id,), fetch='one')
        embed = discord.Embed(title=f"Apodos de {miembro.name}", color=discord.Color.purple())
        if apodos:
            embed.add_field(name="Día ☀️", value=f"`{apodos['apodo_dia']}`" if apodos['apodo_dia'] else "No asignado", inline=True)
            embed.add_field(name="Tarde 🌅", value=f"`{apodos['apodo_tarde']}`" if apodos['apodo_tarde'] else "No asignado", inline=True)
            embed.add_field(name="Noche 🌑", value=f"`{apodos['apodo_noche']}`" if apodos['apodo_noche'] else "No asignado", inline=True)
        else:
            embed.description = "Este usuario no tiene apodos asignados."
        await ctx.send(embed=embed)

    @commands.command(name='quitarapodo', help='Elimina el apodo de un usuario para un turno. Uso: !quitarapodo <miembro> <dia|tarde|noche>')
    @commands.has_permissions(administrator=True)
    async def quitarapodo(self, ctx, miembro: discord.Member, turno: str):
        turno = turno.lower()
        if turno not in ['dia', 'tarde', 'noche']:
            await ctx.send("❌ Turno inválido. Usa `dia`, `tarde` o `noche`."); return
        query = f"UPDATE apodos_operador SET apodo_{turno} = NULL WHERE user_id = %s AND apodo_{turno} IS NOT NULL"
        rows = await db_execute(query, (miembro.id,))
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
        for row in todos_los_apodos:
            if not any([row['apodo_dia'], row['apodo_tarde'], row['apodo_noche']]): continue
            miembro = ctx.guild.get_member(row['user_id'])
            nombre_operador = miembro.mention if miembro else f"ID: {row['user_id']}"
            dia_str = f"`{row['apodo_dia']}`" if row['apodo_dia'] else "N/A"
            tarde_str = f"`{row['apodo_tarde']}`" if row['apodo_tarde'] else "N/A"
            noche_str = f"`{row['apodo_noche']}`" if row['apodo_noche'] else "N/A"
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
        placeholders = ','.join('%s' for _ in perfiles_a_verificar)
        perfiles_existentes_rows = await db_execute(f"SELECT nombre FROM personas WHERE nombre IN ({placeholders})", tuple(perfiles_a_verificar), fetch='all')
        nombres_perfiles_existentes = {row['nombre'] for row in perfiles_existentes_rows}
        perfiles_no_encontrados = [p for p in perfiles_a_verificar if p not in nombres_perfiles_existentes]
        if perfiles_no_encontrados:
            await ctx.send(f"❌ Los siguientes perfiles no existen: `{', '.join(perfiles_no_encontrados)}`. Créalos primero con `!crearperfil`."); return
        reporte = ""
        for mencion, perfil in pares:
            try:
                miembro = await commands.MemberConverter().convert(ctx, mencion)
                rows_affected = await db_execute("INSERT INTO operador_perfil (user_id, nombre_perfil) VALUES (%s, %s) ON CONFLICT (user_id, nombre_perfil) DO NOTHING", (miembro.id, perfil))
                if rows_affected > 0:
                    reporte += f"✅ **Asignado a {miembro.mention}**: `{perfil}`\n"
                else:
                    reporte += f"🤔 **{miembro.mention} ya tenía asignado**: `{perfil}`\n"
            except commands.MemberNotFound:
                reporte += f"⚠️ **No se encontró al miembro**: `{mencion}`\n"
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
                rows = await db_execute("DELETE FROM operador_perfil WHERE user_id = %s AND nombre_perfil = %s", (miembro.id, perfil))
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
            
            perfiles_lista = [row['nombre'] for row in perfiles_rows]
            operadores = [m for m in ctx.guild.members if not m.bot]
            
            print(f"[SYNC] Encontrados {len(perfiles_lista)} perfiles y {len(operadores)} operadores.")

            if not operadores:
                await ctx.send("❌ No se encontraron operadores en el servidor."); return

            nuevas_asignaciones = 0
            for operador in operadores:
                for perfil in perfiles_lista:
                    rows_affected = await db_execute(
                        "INSERT INTO operador_perfil (user_id, nombre_perfil) VALUES (%s, %s) ON CONFLICT (user_id, nombre_perfil) DO NOTHING",
                        (operador.id, perfil)
                    )
                    if rows_affected > 0:
                        nuevas_asignaciones += 1
            
            print(f"[SYNC] Finalizado. Se realizaron {nuevas_asignaciones} nuevas asignaciones.")
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
        perfiles = await db_execute("SELECT nombre_perfil FROM operador_perfil WHERE user_id = %s ORDER BY nombre_perfil ASC", (target_user.id,), fetch='all')
        if perfiles:
            lista_perfiles = "\n".join([f"- `{p['nombre_perfil']}`" for p in perfiles])
            embed = discord.Embed(title=f"Perfiles de {target_user.name}", description=lista_perfiles, color=discord.Color.blue())
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"🤔 {target_user.name} no tiene perfiles asignados.")

async def setup(bot):
    await bot.add_cog(ProfileCog(bot))
