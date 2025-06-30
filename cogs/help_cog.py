import discord
from discord.ext import commands
from utils.db_manager import db_execute

class HelpView(discord.ui.View):
    def __init__(self, context, mapping, visible_categories):
        super().__init__(timeout=120.0)
        self.context = context
        self.mapping = mapping
        self.message = None
        self.add_item(CategorySelect(visible_categories))

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

class CategorySelect(discord.ui.Select):
    def __init__(self, categories):
        self.categories = categories
        options = [discord.SelectOption(label=cat_name, description=f"Ver comandos de {cat_name}") for cat_name in categories.keys()]
        super().__init__(placeholder="Elige una categoría para ver sus comandos...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.view.context.author:
            await interaction.response.send_message("No puedes usar este menú de ayuda.", ephemeral=True)
            return

        selected_category = self.values[0]
        commands_in_category = self.categories[selected_category]

        embed = discord.Embed(title=f"Comandos en: {selected_category}", color=discord.Color.blue())
        embed.set_footer(text="Usa !help <comando> para más detalles sobre un comando específico.")
        
        description = ""
        if selected_category == "Comandos Personalizados":
            description = ", ".join([f"`{cmd_name}`" for cmd_name in commands_in_category])
        else:
            for command in commands_in_category:
                description += f"**`{self.view.context.prefix}{command.name}`**: {command.help or 'Sin descripción.'}\n"
        
        embed.description = description if description else "No hay comandos disponibles en esta categoría."
        
        await interaction.response.edit_message(embed=embed)

class MyHelpCommand(commands.HelpCommand):
    async def _get_visible_categories(self):
        """Obtiene las categorías y comandos visibles para el usuario de forma asíncrona."""
        configs_rows = await db_execute("SELECT nombre_comando, estado FROM comandos_config", fetch='all')
        configs = {row['nombre_comando']: row['estado'] for row in configs_rows} if configs_rows else {}
        
        perms_rows = await db_execute("SELECT nombre_comando FROM permisos_comandos WHERE user_id = %s", (self.context.author.id,), fetch='all')
        perms = [row['nombre_comando'] for row in perms_rows] if perms_rows else []

        custom_cmds_rows = await db_execute("SELECT nombre_comando FROM comandos_dinamicos ORDER BY nombre_comando ASC", fetch='all')
        custom_cmds = [row['nombre_comando'] for row in custom_cmds_rows] if custom_cmds_rows else []

        es_admin = self.context.author.guild_permissions.administrator
        
        all_categories = {
            "Gestión de Operadores": ['apodo', 'verapodo', 'quitarapodo', 'listaapodos', 'asignar', 'desasignar', 'misperfiles', 'lm', 'sincronizar-perfiles', 'desincronizar-perfiles'],
            "Estadísticas y Registros": ['estadisticas', 'registrolm', 'exito', 'verexitos'],
            "Gestión de Perfiles (IA)": ['crearperfil', 'borrarperfil', 'listaperfiles', 'agghistorial', 'verinfo'],
            "Análisis con IA": ['reply', 'consejo', 'preguntar'],
            "Audio (ElevenLabs)": ['sync_elevenlabs', 'audio', 'audiolab'],
            "Memoria del Bot": ['guardar', 'buscar', 'resumir'],
            "Tareas Programadas": ['programar', 'programar-ia', 'programar-serie', 'tareas', 'borrartarea'],
            "Administración General": ['backup', 'privatizar', 'publicar', 'permitir', 'denegar', 'estado_comandos', 'anuncio', 'aggregla', 'listareglas', 'borrarregla', 'exportar-config', 'importar-config'],
            "Comandos Personalizados": custom_cmds
        }

        visible_categories = {}
        for cat_name, cmd_list in all_categories.items():
            visible_cmds = []
            if not cmd_list: continue

            for cmd_name in cmd_list:
                command = self.context.bot.get_command(cmd_name)
                if command and not command.hidden:
                    estado_cmd = configs.get(command.name, 'publico')
                    if es_admin or estado_cmd == 'publico' or command.name in perms:
                        visible_cmds.append(command)
                elif cat_name == "Comandos Personalizados" and cmd_name in custom_cmds:
                    visible_cmds.append(cmd_name)

            if visible_cmds:
                visible_categories[cat_name] = visible_cmds
        
        return visible_categories

    def get_command_signature(self, command):
        return f'{self.context.prefix}{command.name} {command.signature}'

    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="🤖 Menú de Ayuda de MiBotGemini 🤖", color=discord.Color.dark_purple())
        embed.description = "Selecciona una categoría del menú desplegable para ver sus comandos.\nUsa `!help <comando>` para obtener información detallada sobre un comando específico."
        visible_categories = await self._get_visible_categories()
        view = HelpView(self.context, mapping, visible_categories)
        view.message = await self.get_destination().send(embed=embed, view=view)

    async def send_command_help(self, command):
        if command.hidden:
            return
        
        embed = discord.Embed(title=f"Ayuda para: `!{command.name}`", color=discord.Color.dark_green())
        
        alias = ", ".join([f"`{a}`" for a in command.aliases])
        if alias:
            embed.add_field(name="Alias", value=alias, inline=False)

        usage = f"`{self.get_command_signature(command)}`"
        embed.add_field(name="Uso", value=usage, inline=False)

        if command.help:
            embed.add_field(name="Descripción", value=command.help, inline=False)

        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error):
        embed = discord.Embed(title="Error de Ayuda", description=error, color=discord.Color.red())
        await self.get_destination().send(embed=embed)

    async def command_not_found(self, string):
        result = await db_execute("SELECT respuesta_comando, creador_nombre FROM comandos_dinamicos WHERE nombre_comando = %s", (string,), fetch='one')
        
        if result:
            respuesta, creador = result['respuesta_comando'], result['creador_nombre']
            embed = discord.Embed(title=f"Ayuda para Comando Personalizado: `!{string}`", color=discord.Color.dark_blue())
            embed.add_field(name="Respuesta", value=f"```{respuesta}```", inline=False)
            embed.add_field(name="Creador", value=creador, inline=False)
            await self.get_destination().send(embed=embed)
        else:
            await self.send_error_message(f'No se encontró ningún comando llamado "{string}".')

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._original_help_command = bot.help_command
        bot.help_command = MyHelpCommand()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self._original_help_command

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
