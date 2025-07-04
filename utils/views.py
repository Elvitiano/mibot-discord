import discord

class PaginationView(discord.ui.View):
    """Una vista para paginar embeds con botones de Anterior/Siguiente."""
    def __init__(self, ctx, pages, title, color=discord.Color.blue()):
        super().__init__(timeout=180.0)
        self.ctx = ctx
        self.pages = pages
        self.title = title
        self.color = color
        self.current_page = 0
        self.total_pages = len(self.pages)
        self.message = None
        self.update_buttons()

    def update_buttons(self):
        """Habilita o deshabilita los botones según la página actual."""
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page >= self.total_pages - 1

    def create_embed(self):
        """Crea el embed para la página actual."""
        embed = discord.Embed(
            title=self.title,
            description=self.pages[self.current_page],
            color=self.color
        )
        embed.set_footer(text=f"Página {self.current_page + 1} de {self.total_pages}")
        return embed

    async def start(self):
        """Envía el mensaje inicial con la primera página."""
        self.message = await self.ctx.send(embed=self.create_embed(), view=self)

    async def on_timeout(self):
        """Elimina los botones cuando la vista expira."""
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("No puedes usar estos botones.", ephemeral=True)
            return
        
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Siguiente", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("No puedes usar estos botones.", ephemeral=True)
            return

        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)
