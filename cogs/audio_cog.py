import discord
from discord.ext import commands
import asyncio
import re
import io

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
            else:
                prompt = f'{base_prompt}\n**IMPORTANT INSTRUCTION:** Please generate a new, different and creative alternative to the previous suggestion.\n**ORIGINAL TEXT:** "{original_text}"'

            response = await ctx.bot.gemini_model.generate_content_async(prompt)
            
            try:
                text_content = response.text
            except ValueError:
                print(f"Respuesta de IA bloqueada en get_refined_script. Razón: {response.prompt_feedback}")
                await ctx.send("❌ La respuesta de la IA fue bloqueada por seguridad. No se puede generar el guion.")
                if msg_to_edit:
                    await msg_to_edit.delete()
                return None

            parts = text_content.split('---')
            script_with_tags = re.sub(r'\*\*', '', parts[0]).strip()
            clean_script = re.sub(r'\[.*?\]', '', script_with_tags).strip()

            embed = discord.Embed(title="🎬 Guion Propuesto 🎬", color=discord.Color.blurple())
            embed.add_field(name="1️⃣ Versión con Etiquetas (Experimental)", value=f"```\n{script_with_tags}\n```", inline=False)
            embed.add_field(name="2️⃣ Versión Limpia (Recomendada)", value=f"```\n{clean_script}\n```", inline=False)
            embed.set_footer(text="Reacciona con 🔄 para regenerar, o elige la versión para el audio.")
            
            if is_first_run:
                msg_to_edit = await ctx.send(embed=embed)
                is_first_run = False
            else:
                await msg_to_edit.edit(embed=embed)

            await msg_to_edit.add_reaction("🔄"); await msg_to_edit.add_reaction("1️⃣"); await msg_to_edit.add_reaction("2️⃣")

            def check(r, u): return u == ctx.author and str(r.emoji) in ["🔄", "1️⃣", "2️⃣"] and r.message.id == msg_to_edit.id
            try:
                reaction, _ = await ctx.bot.wait_for('reaction_add', timeout=180.0, check=check)
                
                if str(reaction.emoji) == "🔄":
                    await msg_to_edit.clear_reactions()
                    continue

                chosen_script = script_with_tags if str(reaction.emoji) == "1️⃣" else clean_script
                
                final_embed = discord.Embed(title="📝 Guion Final Seleccionado", description=f"```\n{chosen_script}\n```", color=discord.Color.green())
                final_embed.set_footer(text="Puedes copiar este texto.")
                await msg_to_edit.edit(embed=final_embed)
                await msg_to_edit.clear_reactions()
                return chosen_script

            except asyncio.TimeoutError:
                await msg_to_edit.delete()
                await ctx.send("Tiempo de espera agotado.", delete_after=10)
                return None

class AudioCog(commands.Cog, name="Audio"):
    """Comandos para la generación de audio con ElevenLabs."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='sync_elevenlabs', help='(Admin) Sincroniza las voces de ElevenLabs.')
    @commands.has_permissions(administrator=True)
    async def sync_elevenlabs(self, ctx):
        if not self.bot.elevenlabs_client: await ctx.send("❌ Cliente de ElevenLabs no configurado."); return
        async with ctx.typing():
            try:
                voices = await asyncio.to_thread(self.bot.elevenlabs_client.voices.get_all)
                self.bot.elevenlabs_voices.clear()
                my_voices = [v for v in voices.voices if v.category != 'premade']
                emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"] + [chr(0x1f1e6 + i) for i in range(26)]
                description = "Tus voces personalizadas han sido sincronizadas:\n\n"
                for i, voice in enumerate(my_voices):
                    if i < len(emojis):
                        self.bot.elevenlabs_voices[emojis[i]] = {'id': voice.voice_id, 'name': voice.name}
                        description += f"{emojis[i]} **{voice.name}**\n"
                if not self.bot.elevenlabs_voices: await ctx.send("🤔 No se encontraron voces personalizadas en tu cuenta."); return
                embed = discord.Embed(title="🎙️ Librería de Voces Personalizadas Actualizada 🎙️", description=description, color=discord.Color.brand_green())
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send("❌ Error al sincronizar voces."); print(f"Error en !sync_elevenlabs: {e}")

    @commands.command(name='audio', help='Corrige y refina un texto para un guion.')
    async def audio(self, ctx, *, texto: str):
        async with ctx.typing():
            await get_refined_script(ctx, texto)

    @commands.command(name='audiolab', help='(Privado) Genera un audio completo desde un texto.')
    @commands.has_permissions(administrator=True)
    async def audiolab(self, ctx, *, texto: str):
        if not self.bot.elevenlabs_client: await ctx.send("❌ Cliente de ElevenLabs no configurado."); return
        if not self.bot.elevenlabs_voices: await ctx.send("❌ No hay voces sincronizadas. Usa `!sync_elevenlabs`."); return

        final_script = await get_refined_script(ctx, texto)
        if not final_script: return

        description = "Guion aceptado. Selecciona una voz:\n\n" + "\n".join(f"{e} **{v['name']}**" for e, v in self.bot.elevenlabs_voices.items())
        embed = discord.Embed(title="🎤 Selección de Voz 🎤", description=description, color=discord.Color.teal())
        voice_msg = await ctx.send(embed=embed)
        for emoji in self.bot.elevenlabs_voices.keys(): await voice_msg.add_reaction(emoji)
        
        def check_voice(r, u): return u == ctx.author and str(r.emoji) in self.bot.elevenlabs_voices and r.message.id == voice_msg.id
        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=120.0, check=check_voice)
            voice_id = self.bot.elevenlabs_voices[str(reaction.emoji)]['id']
            voice_name = self.bot.elevenlabs_voices[str(reaction.emoji)]['name']
            await voice_msg.delete()

            while True:
                generating_msg = await ctx.send(f"🎙️ Generando audio con la voz de **{voice_name}**...")
                try:
                    def generate_audio_bytes():
                        audio_stream = self.bot.elevenlabs_client.text_to_speech.convert(voice_id=voice_id, text=final_script)
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
                    regen_reaction, _ = await self.bot.wait_for('reaction_add', timeout=180.0, check=check_audio_regen)
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

async def setup(bot):
    await bot.add_cog(AudioCog(bot))
