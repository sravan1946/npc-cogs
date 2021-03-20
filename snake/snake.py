from typing import Literal
import discord
from redbot.core import commands
from redbot.core.bot import Red
from .utils import BoardMenu

RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

# Notes:
# If something doesn't edit the board, it goes into utils, else it's in the game class


class Snake(commands.Cog):
    """
    A simple Snake Game
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot

    @commands.command()
    async def snake(self, ctx):
        menu = BoardMenu(clear_reactions_after=True)
        await menu.start(ctx, wait=True)

    async def make_board(self, ctx):
        pass

    async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
        # TODO: Replace this with the proper end user data removal handling.
        super().red_delete_data_for_user(requester=requester, user_id=user_id)
