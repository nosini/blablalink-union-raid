# SPDX-License-Identifier: AGPL-3.0-or-later

"""Discord bot: slash commands that show the data held by the raid server.

Needs DISCORD_TOKEN, RAID_URL and RAID_READ_TOKEN. It connects out to Discord,
so it needs no open port.
"""

import os

import aiohttp
import discord
from discord import app_commands

LIMIT = 1900  # a message holds 2000 characters; leave room for the fence


def chunks(text):
    """Split on line breaks so that each part fits in one code block."""
    part = ""
    for line in text.splitlines():
        if part and len(part) + len(line) + 1 > LIMIT:
            yield part
            part = ""
        part += line + "\n"
    if part:
        yield part


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.none())
        self.tree = app_commands.CommandTree(self)
        self.http_session = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(
            os.environ["RAID_URL"].rstrip("/"),
            headers={"Authorization": f"Bearer {os.environ['RAID_READ_TOKEN']}"},
            timeout=aiohttp.ClientTimeout(total=30))
        await self.tree.sync()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()


bot = Bot()
raid = app_commands.Group(name="raid", description="Union Raid damage")


async def show(interaction, path, **params):
    await interaction.response.defer(thinking=True)
    params = {k: v for k, v in params.items() if v is not None}
    try:
        async with bot.http_session.get(path, params=params) as response:
            text = (await response.text()).rstrip()
            ok = response.status == 200
    except aiohttp.ClientError:
        text, ok = "the raid server can't be reached", False
    if not ok:
        await interaction.followup.send(f"Error: {text[:500]}")
        return
    for part in chunks(text):
        await interaction.followup.send(f"```\n{part}```")


@raid.command(description="List the stored seasons")
async def seasons(interaction: discord.Interaction):
    await show(interaction, "/seasons")


@raid.command(description="Damage per member for a season (default: latest)")
async def season(interaction: discord.Interaction, season: str | None = None):
    await show(interaction, "/report", season=season)


@raid.command(description="Damage for one day (1-based)")
async def day(interaction: discord.Interaction, day: int,
              season: str | None = None):
    await show(interaction, "/report", day=day, season=season)


@raid.command(description="One member's damage")
async def member(interaction: discord.Interaction, name: str,
                 season: str | None = None):
    await show(interaction, "/report", member=name, season=season)


@raid.command(description="Rank changes between two seasons (default: last two)")
async def compare(interaction: discord.Interaction, old: str | None = None,
                  new: str | None = None):
    await show(interaction, "/compare", **{"from": old, "to": new})


bot.tree.add_command(raid)

if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
