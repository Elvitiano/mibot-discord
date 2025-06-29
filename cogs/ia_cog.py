import discord
from discord.ext import commands
import sqlite3
import io
import asyncio
from PIL import Image
from utils.db_manager import db_execute

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

class IACog(commands.Cog, name="IA"):
    """Comandos que utilizan la IA de Gemini para análisis y generación de texto."""
    def __init__(self, bot):
        self.bot = bot

    # --- Comandos de Gestión de Perfiles y Reglas ---
    @commands.command(name='crearperfil', help='Crea uno o más perfiles. Uso: !crearperfil <nombre1> [nombre2] ...')
    @commands.has_permissions(administrator=True)
    async def crear_perfil(self, ctx, *, nombres: str):
        if not nombres:
            await ctx.send("❌ Debes especificar al menos un nombre de perfil."); return
        nombres_lista = [n.lower() for n in nombres.split()]
        creados, existentes = [], []
        for nombre in nombres_lista:
            try:
                await db_execute("INSERT INTO personas (nombre) VALUES (?)", (nombre,))
                creados.append(nombre)
            except sqlite3.IntegrityError:
                existentes.append(nombre)
        respuesta = ""
        if creados: respuesta += f"✅ Perfiles creados: `{', '.join(creados)}`\n"
        if existentes: respuesta += f"🤔 Perfiles que ya existían: `{', '.join(existentes)}`"
        await ctx.send(respuesta.strip())

    @commands.command(name='agghistorial', help='Añade un dato al historial de un perfil.')
    @commands.has_permissions(administrator=True)
    async def agghistorial(self, ctx, nombre_perfil: str, *, dato: str):
        persona = await db_execute("SELECT id FROM personas WHERE nombre = ?", (nombre_perfil.lower(),), fetch='one')
        if persona:
            await db_execute("INSERT INTO datos_persona (persona_id, dato_texto) VALUES (?, ?)", (persona[0], dato))
            await ctx.send(f"✅ Dato añadido al perfil `{nombre_perfil.lower()}`.")
        else:
            await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`.")

    @commands.command(name='verinfo', help='Muestra la información de un perfil.')
    async def ver_info(self, ctx, nombre_perfil: str):
        persona = await db_execute("SELECT id FROM personas WHERE nombre = ?", (nombre_perfil.lower(),), fetch='one')
        if not persona: await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`."); return
        datos = await db_execute("SELECT dato_texto FROM datos_persona WHERE persona_id = ?",(persona[0],), fetch='all')
        if not datos: await ctx.send(f"El perfil `{nombre_perfil.lower()}` no tiene historial."); return
        embed = discord.Embed(title=f"Historial del Perfil: {nombre_perfil.lower()}", color=discord.Color.orange())
        embed.description = "\n".join([f"- {dato[0]}" for dato in datos])
        await ctx.send(embed=embed)

    @commands.command(name='borrarperfil', help='Borra un perfil y todo su historial.')
    @commands.has_permissions(administrator=True)
    async def borrar_perfil(self, ctx, nombre_perfil: str):
        rows = await db_execute("DELETE FROM personas WHERE nombre = ?", (nombre_perfil.lower(),))
        if rows > 0:
            await ctx.send(f"✅ Perfil `{nombre_perfil.lower()}` y su historial eliminados.")
        else:
            await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`.")
            
    @commands.command(name='listaperfiles', aliases=['verperfiles'], help='Muestra todos los perfiles y a quién están asignados.')
    @commands.has_permissions(administrator=True)
    async def listaperfiles(self, ctx):
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
                menciones = [ctx.guild.get_member(uid).mention if ctx.guild.get_member(uid) else f"ID: {uid}" for uid in usuarios_asignados]
                description += f"👤 **Asignado a:** {', '.join(menciones)}\n\n"
        if len(description) > 4000:
            description = description[:4000] + "\n\n*[Resultados truncados]*"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name='aggregla', help='Añade una regla para la IA.')
    @commands.has_permissions(administrator=True)
    async def aggregla(self, ctx, *, regla: str):
        await db_execute("INSERT INTO reglas_ia (regla_texto) VALUES (?)", (regla,))
        await ctx.send("✅ Nueva regla añadida a la IA.")

    @commands.command(name='listareglas', help='Muestra las reglas de la IA.')
    async def listareglas(self, ctx):
        reglas = await db_execute("SELECT id, regla_texto FROM reglas_ia ORDER BY id ASC", fetch='all')
        if not reglas: await ctx.send("No hay reglas personalizadas para la IA."); return
        embed = discord.Embed(title="Libro de Reglas de la IA", color=discord.Color.light_grey())
        embed.description = "\n".join(f"**{r_id}**: {r_text}" for r_id, r_text in reglas)
        await ctx.send(embed=embed)

    @commands.command(name='borrarregla', help='Borra una regla de la IA por su número.')
    @commands.has_permissions(administrator=True)
    async def borrarregla(self, ctx, regla_id: int):
        rows = await db_execute("DELETE FROM reglas_ia WHERE id = ?", (regla_id,))
        if rows == 0: await ctx.send(f"🤔 No encontré una regla con el ID `{regla_id}`.")
        else: await ctx.send(f"✅ Regla `{regla_id}` borrada.")

    # --- Comandos de IA ---
    @commands.command(name='reply', help='Usa un perfil para analizar una foto/bio.')
    @commands.cooldown(1, 120, commands.BucketType.user) 
    async def reply(self, ctx, nombre_perfil: str = None):
        if not ctx.message.attachments:
            await ctx.send("❌ Debes adjuntar una imagen.", delete_after=10); self.reply.reset_cooldown(ctx); return
        attachment = ctx.message.attachments[0]
        if not attachment.content_type.startswith('image/'):
            await ctx.send("❌ El archivo no es una imagen.", delete_after=10); self.reply.reset_cooldown(ctx); return
        
        async with ctx.typing():
            try:
                image_bytes = await attachment.read()
                hoja_personaje, reglas_ia, image_bytes_procesados = await asyncio.to_thread(
                    process_image_and_db_for_reply, nombre_perfil, image_bytes)
                
                image_for_gemini = {'mime_type': 'image/jpeg', 'data': image_bytes_procesados}
                prompt_dinamico = """**ROL Y OBJETIVO (Wingman Digital):** Tu rol es ser un 'Wingman Digital'. Debes ser ingenioso, observador y seguro, pero nunca arrogante. Tu objetivo es mezclar humor sutil con curiosidad genuina para crear openers de conversación únicos y listos para copiar y pegar.

**REGLAS CRÍTICAS DE COMPORTAMIENTO:**
- **Humor Inteligente:** Prohibido usar expresiones genéricas como 'jajaja' o 'jejeje'. En su lugar, genera humor a través de auto-humor ligero, observaciones ingeniosas o preguntas con un toque de humor.
- **Uso Estratégico de Emojis:** Incluye emojis en un máximo de 2 de las 5 frases de cada opción. Pueden ir al principio, en medio o al final para reforzar el tono. Usa 🤔/👀 para curiosidad, 😉/😏/😂 para complicidad/humor, y 🔥/🙌/🤯 para admiración.
- **Banco de Expresiones Variadas:** Evita repetir "Wow". Usa alternativas como: 'Me quito el sombrero', 'Ojo con eso...', 'Ok, eso es impresionante', 'Uff, qué interesante', 'Vaya, eso sí que no me lo esperaba'.
- **Basado en Evidencia:** Cada opener debe originarse en un detalle VISUAL de la foto o una frase EXACTA de la biografía.
- **Sin Saludos ni Placeholders:** No uses "Hola" ni texto genérico como `[tu hobby]`.

**ESTRUCTURA DE RESPUESTA OBLIGATORIA:**
- Genera dos opciones separadas por `---`.
- La primera debe titularse `**Opción 1:**` y la segunda `**Opción 2:**`.
- Cada opción debe ser una secuencia de 5 frases enumeradas (1., 2., etc.).
- **SALIDA LIMPIA:** No incluyas los nombres de los pasos (como 'El Gancho') en tu respuesta. Solo el texto de la conversación. No uses comillas (`""`).

---
**GUÍA DE ESTILO PARA CADA PASO (Debes seguir esta estructura)**

**Formato A (Secuencia 5 Pasos):**
1.  Empieza con una observación única y detallada. Usa expresiones como "Me quito el sombrero con..." o "Vaya, no esperaba ver...". Ideal para un emoji de admiración (🔥, 👀, 🤯).
2.  Continúa relacionando lo que viste con una experiencia propia de forma graciosa. Ejemplo: "Yo intenté escalar una vez y creo que la pared se rio de mí 😂".
3.  Sigue con una pregunta cerrada, casual y juguetona. Ejemplo: "Así que eres del equipo 'aventura' y no del equipo 'sofá y peli', ¿no? 😉".
4.  Añade una frase que sirva de transición o una suposición juguetona sobre el tema.
5.  Termina con una pregunta abierta y genuina. Puede ser sobre experiencias, gustos, o de forma más directa, sobre lo que buscas en una app de citas. Ejemplos: "Fuera de eso, ¿cuál es tu placer culposo más simple y divertido?" o "Hablando de aventuras, ¿cuál es la cualidad más importante que buscas en un compañero de viaje... o de vida? 😉".

**Formato B (Secuencia Alternativa):**
1.  Empieza con una observación original.
2.  Sigue con una pregunta cerrada y directa sobre la observación.
3.  Añade un comentario ingenioso que aporte valor o contexto.
4.  Continúa relacionando el tema con una experiencia propia de forma graciosa.
5.  Termina con una pregunta abierta que invite a compartir una anécdota o una reflexión ligera sobre citas. Ejemplo: "¿Cuál es la aventura más loca que te gustaría tener con alguien que conozcas aquí?" o "Si tuvieras que describir tu cita ideal con solo 3 emojis, ¿cuáles serían?".
---"""
                if hoja_personaje: prompt_dinamico += f"\n\n**CONTEXTO ADICIONAL (TU PERSONAJE):**\n{hoja_personaje}"
                if reglas_ia: prompt_dinamico += "\n\n**REGLAS ADICIONALES OBLIGATORIAS:**\n" + "\n".join(f"- {regla[0]}" for regla in reglas_ia)
            
                response = await self.bot.gemini_model.generate_content_async([prompt_dinamico, image_for_gemini])
                
                try:
                    text_content = response.text
                except ValueError:
                    print(f"Respuesta de IA bloqueada en !reply. Razón: {response.prompt_feedback}")
                    await ctx.send("❌ La respuesta de la IA fue bloqueada por seguridad. Intenta con otra imagen o prompt.")
                    return

                titulo = f"**Estrategias para `{nombre_perfil.lower()}`:**" if nombre_perfil else "**Estrategias de conversación:**"
                respuesta_final = f"{titulo}\n\n{text_content.replace('---', '\n\n').strip()}"
                await ctx.send(respuesta_final)
            except ValueError as ve: await ctx.send(f"❌ {ve}")
            except Exception as e: print(f"Error en !reply: {e}"); await ctx.send("❌ Error al generar la respuesta.")

    @commands.command(name='consejo', help='Analiza una imagen y da hasta 5 detalles relevantes.')
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def consejo(self, ctx):
        if not ctx.message.attachments:
            await ctx.send("❌ Debes adjuntar una imagen.", delete_after=10); self.consejo.reset_cooldown(ctx); return
        attachment = ctx.message.attachments[0]
        if not attachment.content_type.startswith('image/'):
            await ctx.send("❌ El archivo no es una imagen.", delete_after=10); self.consejo.reset_cooldown(ctx); return
        async with ctx.typing():
            try:
                image_bytes = await attachment.read()
                with Image.open(io.BytesIO(image_bytes)) as img:
                    rgb_img = img.convert('RGB')
                    rgb_img.thumbnail((1024, 1024))
                    buffer = io.BytesIO()
                    rgb_img.save(buffer, format="JPEG")
                    image_bytes_procesados = buffer.getvalue()

                image_for_gemini = {'mime_type': 'image/jpeg', 'data': image_bytes_procesados}
                prompt_consejo = """**ROL Y OBJETIVO (Wingman Digital):** Tu misión es ser un observador agudo. Identifica de 2 a 3 detalles visuales CONCRETOS y únicos en la imagen. Para cada detalle, crea un bloque de conversación con el formato 'Gancho y Profundidad'.

**REGLAS DE ESTILO:**
- **Tono:** Ingenioso, curioso y natural.
- **Formato por Detalle:**
    1.  **El Gancho:** Empieza con una observación carismática sobre el detalle.
    2.  **La Profundidad:** Sigue con una pregunta abierta y genuina relacionada con esa observación.
- **Salida Limpia:** No uses títulos como "Detalle 1" o "Gancho". Sé directo.

**Ejemplo de Salida:**
Ojo con la guitarra que se ve al fondo... ¿Tocas algún clásico de rock o eres más de componer tus propias canciones?
---
Me quito el sombrero con ese cuadro, parece arte abstracto. ¿Qué es lo que más te atrae de una obra de arte?
"""
                response = await self.bot.gemini_model.generate_content_async([prompt_consejo, image_for_gemini])
                
                try:
                    text_content = response.text
                except ValueError:
                    print(f"Respuesta de IA bloqueada en !consejo. Razón: {response.prompt_feedback}")
                    await ctx.send("❌ La respuesta de la IA fue bloqueada por seguridad. Intenta con otra imagen.")
                    return
                
                await ctx.send(f"**Puntos de partida basados en la imagen:**\n\n{text_content}")
            except Exception as e:
                print(f"Error en !consejo: {e}"); await ctx.send("❌ Error al analizar la imagen.")

    @commands.command(name='preguntar', help='Pregúntale algo a la IA.')
    async def preguntar(self, ctx, *, pregunta: str):
        async with ctx.typing():
            try:
                response = await self.bot.gemini_model.generate_content_async(pregunta)
                try:
                    await ctx.send(response.text)
                except ValueError:
                    print(f"Respuesta de IA bloqueada en !preguntar. Razón: {response.prompt_feedback}")
                    await ctx.send("❌ La respuesta de la IA fue bloqueada por seguridad.")
            except Exception as e:
                await ctx.send("❌ Error con la IA de Gemini."); print(f"Error en !preguntar: {e}")

async def setup(bot):
    await bot.add_cog(IACog(bot))
