# SPDX-License-Identifier: AGPL-3.0-or-later

"""Discord bot: slash commands that show the data held by the raid server.

Needs DISCORD_TOKEN, RAID_URL and RAID_READ_TOKEN. It connects out to Discord,
so it needs no open port.

RAID_STYLE picks what `/raid day`, `/raid season` and `/raid compare` send:

- `ansi` (the default): the table as coloured text.
- `image`: the sheet as one PNG image attached to the message, which fits a
  phone where the text tables wrap. Needs the server's Pillow.
- `both`: the coloured text and the image.
- `card`: a link to the server's card page, whose preview shows the image
  too. Needs RAID_PUBLIC_URL, the server's public address, and the
  server's RAID_PUBLIC_CARD=1 so Discord's crawler can read the page.

Member views stay coloured text in every style.
"""

import asyncio
import io
import os
from urllib.parse import urlencode

import aiohttp
import discord
from discord import app_commands

from blablalink_union_raid import sheet

import embeds

# Compose hands an unset RAID_STYLE over as "": treat empty as unset.
STYLE = (os.environ.get("RAID_STYLE") or "ansi").strip().lower()
PUBLIC = os.environ.get("RAID_PUBLIC_URL", "").rstrip("/")

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


async def show(interaction, build, path, table=None, card=None,
               ephemeral=False, **params):
    """Answer a command; `table` builds the sheet, `card` its card query."""
    await interaction.response.defer(thinking=True, ephemeral=ephemeral)
    try:
        data = await fetch(path, **params)
        if table and STYLE in ("image", "both"):
            drawn = table(data)
            image = await sheet_image(card(data))
            if image is None:      # the server cannot draw (or is unreachable)
                await interaction.followup.send(embeds=build(data))
                return
            if STYLE == "image":
                await interaction.followup.send(
                    embed=picture(drawn), file=image)
                return
            await interaction.followup.send(embeds=build(data), file=image)
            return
        if card and STYLE == "card":
            if table:
                # an empty selection raises Empty here: no dead link
                table(data)
            link = card_url(card(data), data)
            await interaction.followup.send(link)   # the preview is the table
            return
        await interaction.followup.send(embeds=build(data))
    except embeds.Empty as exc:
        await interaction.followup.send(f"{exc}")


async def sheet_image(query):
    """The whole sheet as one PNG, or None when the server is down or
    cannot draw it; the caller then sends text instead."""
    try:
        async with bot.http_session.get("/card.png", params=query) as response:
            if response.status != 200:
                return None
            return discord.File(io.BytesIO(await response.read()), "sheet.png")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def picture(table):
    """The small embed that carries the image's title, totals and footer."""
    result = discord.Embed(title=table.title, description=table.intro,
                            colour=embeds.COLOUR)
    if table.gone:    # compare: who has no runs in the newer season
        result.add_field(name="No runs this season", value=", ".join(
            discord.utils.escape_markdown(name)
            for name in table.gone)[:1000], inline=False)
    result.set_footer(text=table.footer)
    return result


def card_url(params, data):
    """The public card page link; `v` busts Discord's preview cache."""
    params = {k: v for k, v in params.items() if v is not None}
    if data.get("ingested_at"):
        params["v"] = data["ingested_at"]
    return f"{PUBLIC}/card?{urlencode(params)}"


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


@raid.command(description="Final day of a season against the last season (default: latest)")
@app_commands.autocomplete(season=season_names)
async def season(interaction: discord.Interaction, season: str | None = None):
    await show(interaction, embeds.season, "/report", table=sheet.season,
               card=lambda data: {"season": data["season"]}, season=season)


@raid.command(description="Damage for one day (1-based)")
@app_commands.autocomplete(season=season_names)
async def day(interaction: discord.Interaction, day: int,
              season: str | None = None):
    # All days are fetched: the change column compares with the day before.
    await show(interaction, lambda data: embeds.day(data, day), "/report",
               table=lambda data: sheet.day(data, day),
               card=lambda data: {"season": data["season"], "day": day},
               season=season)


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
    await show(interaction, embeds.compare, "/compare", table=sheet.compare,
               card=lambda data: {"from": data["from"], "to": data["to"]},
               **{"from": old, "to": new})


@raid.command(description="Your own results over the seasons "
              "(uses your server nickname as your IGN)")
async def me(interaction: discord.Interaction):
    name = interaction.user.display_name
    # Only visible to the caller: it is personal and would clutter the channel.
    await show(interaction, lambda data: embeds.history(data, name),
               "/history", ephemeral=True)


bot.tree.add_command(raid)

if __name__ == "__main__":
    if STYLE not in ("ansi", "image", "card", "both"):
        raise SystemExit(f"RAID_STYLE must be ansi, image, card or both, "
                         f"not {STYLE!r}")
    if STYLE == "card" and not PUBLIC:
        raise SystemExit("RAID_STYLE=card needs RAID_PUBLIC_URL")
    bot.run(os.environ["DISCORD_TOKEN"])
