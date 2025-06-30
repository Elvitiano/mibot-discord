import discord
from discord.ext import commands
import psycopg2
import io
import asyncio
from PIL import Image
from utils.db_manager import db_execute, get_ia_context

class IACog(commands.Cog, name="IA"):
    """
    Este Cog maneja todas las interacciones con la IA de Gemini y la gestión de 'personalidades' o 'perfiles'
    que la IA puede adoptar. Incluye comandos para:
    - Gestión de perfiles (crear, borrar, ver, listar).
    - Gestión del historial/contexto de cada perfil.
    - Gestión de reglas globales para la IA.
    - El comando principal `reply` que usa la IA para analizar una imagen y generar una respuesta de texto.
    """
    def __init__(self, bot):
        self.bot = bot

    # --- Comandos de Gestión de Perfiles y Reglas ---
    @commands.command(name='crearperfil', help='Crea uno o más perfiles. Uso: !crearperfil <nombre1> [nombre2] ...')
    @commands.has_permissions(administrator=True)
    async def crear_perfil(self, ctx, *, nombres: str):
        """
        Crea uno o más perfiles de personaje en la base de datos.
        Solo los administradores pueden usar este comando.
        Los nombres de perfil se guardan en minúsculas para evitar duplicados.
        Informa al usuario qué perfiles se crearon y cuáles ya existían.
        """
        if not nombres:
            await ctx.send("❌ Debes especificar al menos un nombre de perfil."); return
        nombres_lista = [n.lower() for n in nombres.split()]
        creados, existentes = [], []
        for nombre in nombres_lista:
            try:
                rows_affected = await db_execute("INSERT INTO personas (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING", (nombre,))
                if rows_affected > 0:
                    creados.append(nombre)
                else:
                    existentes.append(nombre)
            except Exception as e:
                print(f"Error al crear perfil {nombre}: {e}")
        
        respuesta = ""
        if creados: respuesta += f"✅ Perfiles creados: `{', '.join(creados)}`\n"
        if existentes: respuesta += f"🤔 Perfiles que ya existían: `{', '.join(existentes)}`"
        await ctx.send(respuesta.strip())

    @commands.command(name='agghistorial', help='Añade un dato al historial de un perfil.')
    @commands.has_permissions(administrator=True)
    async def agghistorial(self, ctx, nombre_perfil: str, *, dato: str):
        """
        Añade una pieza de información (un 'dato') al historial de un perfil existente.
        Este historial se usará como contexto para la IA en el comando `reply`.
        Solo los administradores pueden usar este comando.
        """
        persona = await db_execute("SELECT id FROM personas WHERE nombre = %s", (nombre_perfil.lower(),), fetch='one')
        if persona:
            await db_execute("INSERT INTO datos_persona (persona_id, dato_texto) VALUES (%s, %s)", (persona['id'], dato))
            await ctx.send(f"✅ Dato añadido al perfil `{nombre_perfil.lower()}`.")
        else:
            await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`.")

    @commands.command(name='verinfo', help='Muestra la información de un perfil.')
    async def ver_info(self, ctx, nombre_perfil: str):
        """
        Muestra todo el historial de datos asociado a un perfil específico.
        La información se presenta en un embed de Discord para mayor claridad.
        Cualquier usuario puede usar este comando.
        """
        persona = await db_execute("SELECT id FROM personas WHERE nombre = %s", (nombre_perfil.lower(),), fetch='one')
        if not persona: await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`."); return
        datos = await db_execute("SELECT dato_texto FROM datos_persona WHERE persona_id = %s",(persona['id'],), fetch='all')
        if not datos: await ctx.send(f"El perfil `{nombre_perfil.lower()}` no tiene historial."); return
        embed = discord.Embed(title=f"Historial del Perfil: {nombre_perfil.lower()}", color=discord.Color.orange())
        embed.description = "\n".join([f"- {dato['dato_texto']}" for dato in datos])
        await ctx.send(embed=embed)

    @commands.command(name='borrarperfil', help='Borra un perfil y todo su historial.')
    @commands.has_permissions(administrator=True)
    async def borrar_perfil(self, ctx, nombre_perfil: str):
        """
        Elimina permanentemente un perfil y todo su historial de la base de datos.
        Debido a la configuración de la base de datos (ON DELETE CASCADE),
        al borrar la persona se borran también sus datos asociados.
        Solo los administradores pueden usar este comando.
        """
        rows = await db_execute("DELETE FROM personas WHERE nombre = %s", (nombre_perfil.lower(),))
        if rows > 0:
            await ctx.send(f"✅ Perfil `{nombre_perfil.lower()}` y su historial eliminados.")
        else:
            await ctx.send(f"❌ No encontré el perfil `{nombre_perfil.lower()}`.")
            
    @commands.command(name='listaperfiles', aliases=['verperfiles'], help='Muestra todos los perfiles y a quién están asignados.')
    @commands.has_permissions(administrator=True)
    async def listaperfiles(self, ctx):
        """
        Lista todos los perfiles existentes en la base de datos.
        Además, muestra a qué operadores (usuarios de Discord) está asignado cada perfil,
        si es que hay alguna asignación.
        Solo los administradores pueden usar este comando.
        """
        perfiles = await db_execute("SELECT nombre FROM personas ORDER BY nombre ASC", fetch='all')
        if not perfiles:
            await ctx.send("No hay perfiles creados en la base de datos."); return
        asignaciones = await db_execute("SELECT nombre_perfil, user_id FROM operador_perfil", fetch='all')
        mapa_asignaciones = {}
        for row in asignaciones:
            nombre_perfil, user_id = row['nombre_perfil'], row['user_id']
            if nombre_perfil not in mapa_asignaciones:
                mapa_asignaciones[nombre_perfil] = []
            mapa_asignaciones[nombre_perfil].append(user_id)
        embed = discord.Embed(title="📊 Estado de Asignación de Perfiles", color=discord.Color.blue())
        description = ""
        for perfil_tuple in perfiles:
            nombre_perfil = perfil_tuple['nombre']
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
        """
        Añade una regla global que la IA deberá seguir en todas sus generaciones.
        Estas reglas se añaden al final del prompt del sistema.
        Solo los administradores pueden usar este comando.
        """
        await db_execute("INSERT INTO reglas_ia (regla_texto) VALUES (%s)", (regla,))
        await ctx.send("✅ Nueva regla añadida a la IA.")

    @commands.command(name='listareglas', help='Muestra las reglas de la IA.')
    async def listareglas(self, ctx):
        """
        Muestra todas las reglas globales de la IA que están actualmente en la base de datos.
        Cada regla se muestra con su ID, que se puede usar para borrarla.
        Cualquier usuario puede usar este comando.
        """
        reglas = await db_execute("SELECT id, regla_texto FROM reglas_ia ORDER BY id ASC", fetch='all')
        if not reglas: await ctx.send("No hay reglas personalizadas para la IA."); return
        embed = discord.Embed(title="Libro de Reglas de la IA", color=discord.Color.light_grey())
        embed.description = "\n".join(f"**{r['id']}**: {r['regla_texto']}" for r in reglas)
        await ctx.send(embed=embed)

    @commands.command(name='borrarregla', help='Borra una regla de la IA por su número.')
    @commands.has_permissions(administrator=True)
    async def borrarregla(self, ctx, regla_id: int):
        """
        Elimina una regla global de la IA usando su ID numérico.
        Solo los administradores pueden usar este comando.
        """
        rows = await db_execute("DELETE FROM reglas_ia WHERE id = %s", (regla_id,))
        if rows == 0: await ctx.send(f"🤔 No encontré una regla con el ID `{regla_id}`.")
        else: await ctx.send(f"✅ Regla `{regla_id}` borrada.")

    # --- Comandos de IA ---
    @commands.command(name='reply', help='Usa un perfil para analizar una foto/bio.')
    @commands.cooldown(1, 120, commands.BucketType.user) 
    async def reply(self, ctx, nombre_perfil: str = None):
        """
        Comando principal de IA. Analiza una imagen adjunta y genera una respuesta de texto.
        Tiene un cooldown de 120 segundos por usuario para evitar el abuso.

        Pasos que sigue:
        1. Valida que se haya adjuntado una imagen.
        2. Muestra el indicador de "escribiendo..." para feedback al usuario.
        3. Procesa la imagen: la lee, la convierte a RGB, la redimensiona y la prepara para la IA.
        4. Obtiene el contexto de la IA: el historial del perfil (si se especifica) y las reglas globales.
        5. Construye un prompt muy detallado y estructurado para guiar a la IA (Gemini).
        6. Envía el prompt y la imagen a la IA.
        7. Recibe la respuesta de la IA y la envía al canal de Discord.
        8. Maneja posibles errores en cada paso.
        """
        if not ctx.message.attachments:
            await ctx.send("❌ Debes adjuntar una imagen.", delete_after=10); self.reply.reset_cooldown(ctx); return
        attachment = ctx.message.attachments[0]
        if not attachment.content_type.startswith('image/'):
            await ctx.send("❌ El archivo no es una imagen.", delete_after=10); self.reply.reset_cooldown(ctx); return
        
        async with ctx.typing():
            try:
                # --- 1. Procesamiento de la Imagen ---
                image_bytes = await attachment.read()
                
                # Convertir, redimensionar y comprimir la imagen para optimizarla para la IA
                with Image.open(io.BytesIO(image_bytes)) as img:
                    rgb_img = img.convert('RGB')
                    rgb_img.thumbnail((1024, 1024))
                    buffer = io.BytesIO()
                    rgb_img.save(buffer, format="JPEG")
                    image_bytes_procesados = buffer.getvalue()

                # --- 2. Obtención de Contexto desde la BD ---
                # Se recupera el historial del perfil y las reglas globales de la IA.
                hoja_personaje, reglas_ia_rows = await get_ia_context(nombre_perfil)
                
                image_for_gemini = {'mime_type': 'image/jpeg', 'data': image_bytes_procesados}
                
                # --- 3. Construcción del Prompt Dinámico ---
                # Este es el cerebro del comando. Define el rol, las reglas y el formato de salida de la IA.
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
5.  Termina con una pregunta abierta que invite a compartir una anécdota o una reflexión ligera sobre citas. Ejemplo: "¿Cuál es la aventura más loca que te gustaría tener con alguien que conozcas aquí?"
---"""

                # Se añade el contexto del perfil y las reglas al final del prompt base.
                if hoja_personaje: prompt_dinamico += f"\n\n**CONTEXTO ADICIONAL (TU PERSONAJE):**\n{hoja_personaje}"
                if reglas_ia_rows: prompt_dinamico += "\n\n**REGLAS ADICIONALES OBLIGATORIAS:**\n" + "\n".join(f"- {regla['regla_texto']}" for regla in reglas_ia_rows)
            
                # --- 4. Llamada a la API de Gemini ---
                response = await self.bot.gemini_model.generate_content_async([prompt_dinamico, image_for_gemini])
                
                # --- 5. Envío de la Respuesta ---
                # Accedemos al texto de la respuesta de forma segura y lo enviamos al canal.
                try:
                    respuesta_texto = response.text
                    await ctx.send(respuesta_texto)
                except Exception as e:
                    await ctx.send(f"Error al procesar la respuesta de la IA: {str(e)}")
                    print(f"Error en el contenido de la respuesta de Gemini: {response.prompt_feedback}")


            except Exception as e:
                # --- 6. Manejo de Errores General ---
                await ctx.send(f"Error general en el comando reply: {str(e)}")
                print(f"Error general en el comando reply: {str(e)}")


async def setup(bot):
    await bot.add_cog(IACog(bot))
