# SPDX-License-Identifier: AGPL-3.0-or-later

"""Discord bot: slash commands that show the data held by the raid server.

Needs DISCORD_TOKEN, RAID_URL and RAID_READ_TOKEN. It connects out to Discord,
so it needs no open port.
"""

import os

import aiohttp
import discord
from discord import app_commands

import embeds

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


async def fetch(path, **params):
    """The server's JSON, or an Error message for the user."""
    params = {k: v for k, v in params.items() if v is not None}
    params["format"] = "json"
    try:
        async with bot.http_session.get(path, params=params) as response:
            if response.status == 200:
                return await response.json()
            text = (await response.text()).strip()
    except aiohttp.ClientError:
        text = "the raid server can't be reached"
    raise embeds.Empty(text[:500])


async def show(interaction, build, path, **params):
    await interaction.response.defer(thinking=True)
    try:
        await interaction.followup.send(
            embeds=build(await fetch(path, **params)))
    except embeds.Empty as exc:
        await interaction.followup.send(f"{exc}")


async def season_names(interaction, current):
    try:
        found = await fetch("/seasons")
    except embeds.Empty:
        return []
    names = [s["name"] for s in reversed(found)]
    return [app_commands.Choice(name=n, value=n) for n in names
            if current.casefold() in n.casefold()][:25]


@raid.command(description="List the stored seasons")
async def seasons(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        found = await fetch("/seasons")
    except embeds.Empty as exc:
        await interaction.followup.send(f"{exc}")
        return
    lines = [f"**{s['name']}** · {embeds.short(s['total'])} · "
             f"{s['members']} members" for s in reversed(found)]
    await interaction.followup.send(embed=discord.Embed(
        title="Union Raid seasons", colour=embeds.COLOUR,
        description="\n".join(lines) or "No seasons stored yet."))


@raid.command(description="Ranking for a season (default: the latest)")
@app_commands.autocomplete(season=season_names)
async def season(interaction: discord.Interaction, season: str | None = None):
    await show(interaction, embeds.season, "/report", season=season)


@raid.command(description="Damage for one day (1-based)")
@app_commands.autocomplete(season=season_names)
async def day(interaction: discord.Interaction, day: int,
              season: str | None = None):
    await show(interaction, lambda data: embeds.day(data, day), "/report",
               day=day, season=season)


@raid.command(description="One member's runs")
@app_commands.autocomplete(season=season_names)
async def member(interaction: discord.Interaction, name: str,
                 season: str | None = None):
    await show(interaction, embeds.member, "/report", member=name,
               season=season)


@raid.command(description="Rank changes between two seasons (default: last two)")
@app_commands.autocomplete(old=season_names, new=season_names)
async def compare(interaction: discord.Interaction, old: str | None = None,
                  new: str | None = None):
    await show(interaction, embeds.compare, "/compare",
               **{"from": old, "to": new})


bot.tree.add_command(raid)

if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
