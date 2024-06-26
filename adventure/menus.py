from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

import discord
from discord import Interaction
from discord._types import ClientT
from redbot.core.commands import commands
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import box, escape, humanize_number
from redbot.vendored.discord.ext import menus

from .charsheet import Character, Item
from .constants import Rarities, ANSI_ESCAPE, ANSI_CLOSE, ANSITextColours, Slot
from .converters import process_argparse_stat

from .bank import bank
from .charsheet import Character
from .helpers import is_dev, smart_embed

if TYPE_CHECKING:
    from .abc import AdventureMixin
    from .charsheet import BackpackTable

_ = Translator("Adventure", __file__)
log = logging.getLogger("red.cogs.adventure.menus")

SELL_CONFIRM_AMOUNT = -420


class LeaderboardSource(menus.ListPageSource):
    def __init__(self, entries: List[Tuple[int, Dict]]):
        super().__init__(entries, per_page=10)

    def is_paginating(self):
        return True

    async def format_page(self, menu: menus.MenuPages, entries: List[Tuple[int, Dict]]):
        ctx = menu.ctx
        rebirth_len = len(humanize_number(entries[0][1]["rebirths"]))
        start_position = (menu.current_page * self.per_page) + 1
        pos_len = len(str(start_position + 9)) + 2
        rebirth_len = (len("Rebirths") if len("Rebirths") > rebirth_len else rebirth_len) + 2
        set_piece_len = len("Set Pieces") + 2
        level_len = len("Level") + 2
        header = (
            f"{'#':{pos_len}}{'Rebirths':{rebirth_len}}"
            f"{'Level':{level_len}}{'Set Pieces':{set_piece_len}}{'Adventurer':2}"
        )
        author = ctx.author

        if getattr(ctx, "guild", None):
            guild = ctx.guild
        else:
            guild = None

        players = []
        for position, acc in enumerate(entries, start=start_position):
            user_id = acc[0]
            account_data = acc[1]
            if guild is not None:
                member = guild.get_member(user_id)
            else:
                member = None

            if member is not None:
                username = member.display_name
            else:
                user = menu.ctx.bot.get_user(user_id)
                if user is None:
                    username = f"{user_id}"
                else:
                    username = user.name
            username = escape(username, formatting=True)

            if user_id == author.id:
                # Highlight the author's position
                username = f"<<{username}>>"

            pos_str = position
            rebirths = humanize_number(account_data["rebirths"])
            set_items = humanize_number(account_data["set_items"])
            level = humanize_number(account_data["lvl"])
            data = (
                f"{f'{pos_str}.':{pos_len}}"
                f"{rebirths:{rebirth_len}}"
                f"{level:{level_len}}"
                f"{set_items:{set_piece_len}}"
                f"{username}"
            )
            players.append(data)

        embed = discord.Embed(
            title="Adventure Leaderboard",
            color=await menu.ctx.embed_color(),
            description="```md\n{}``` ```md\n{}```".format(
                header,
                "\n".join(players),
            ),
        )
        embed.set_footer(text=f"Page {menu.current_page + 1}/{self.get_max_pages()}")
        return embed


class WeeklyScoreboardSource(menus.ListPageSource):
    def __init__(self, entries: List[Tuple[int, Dict]], stat: Optional[str] = None):
        super().__init__(entries, per_page=10)
        self._stat = stat or "wins"

    def is_paginating(self):
        return True

    async def format_page(self, menu: menus.MenuPages, entries: List[Tuple[int, Dict]]):
        ctx = menu.ctx
        stats_len = len(humanize_number(entries[0][1][self._stat])) + 3
        start_position = (menu.current_page * self.per_page) + 1
        pos_len = len(str(start_position + 9)) + 2
        stats_plural = self._stat if self._stat.endswith("s") else f"{self._stat}s"
        stats_len = (len(stats_plural) if len(stats_plural) > stats_len else stats_len) + 2
        rebirth_len = len("Rebirths") + 2
        header = f"{'#':{pos_len}}{stats_plural.title().ljust(stats_len)}{'Rebirths':{rebirth_len}}{'Adventurer':2}"
        author = ctx.author

        if getattr(ctx, "guild", None):
            guild = ctx.guild
        else:
            guild = None

        players = []
        for position, (user_id, account_data) in enumerate(entries, start=start_position):
            if guild is not None:
                member = guild.get_member(user_id)
            else:
                member = None

            if member is not None:
                username = member.display_name
            else:
                user = menu.ctx.bot.get_user(user_id)
                if user is None:
                    username = user_id
                else:
                    username = user.name
            username = escape(str(username), formatting=True)
            if user_id == author.id:
                # Highlight the author's position
                username = f"<<{username}>>"

            pos_str = position
            rebirths = humanize_number(account_data["rebirths"])
            stats_value = humanize_number(account_data[self._stat.lower()])

            data = f"{f'{pos_str}.':{pos_len}}" f"{stats_value:{stats_len}}" f"{rebirths:{rebirth_len}}" f"{username}"
            players.append(data)

        embed = discord.Embed(
            title=f"Adventure Weekly Scoreboard",
            color=await menu.ctx.embed_color(),
            description="```md\n{}``` ```md\n{}```".format(
                header,
                "\n".join(players),
            ),
        )
        embed.set_footer(text=f"Page {menu.current_page + 1}/{self.get_max_pages()}")
        return embed


class ScoreboardSource(WeeklyScoreboardSource):
    def __init__(self, entries: List[Tuple[int, Dict]], stat: Optional[str] = None):
        super().__init__(entries)
        self._stat = stat or "wins"
        self._legend = None

    def is_paginating(self):
        return True

    async def format_page(self, menu: menus.MenuPages, entries: List[Tuple[int, Dict]]):
        ctx = menu.ctx
        if self._legend is None:
            self._legend = (
                "React with the following to go to the specified filter:\n"
                "\N{FACE WITH PARTY HORN AND PARTY HAT}: Win scoreboard\n"
                "\N{FIRE}: Loss scoreboard\n"
                "\N{DAGGER KNIFE}: Physical attack scoreboard\n"
                "\N{SPARKLES}: Magic attack scoreboard\n"
                "\N{LEFT SPEECH BUBBLE}: Diplomacy scoreboard\n"
                "\N{PERSON WITH FOLDED HANDS}: Pray scoreboard\n"
                "\N{RUNNER}: Run scoreboard\n"
                "\N{EXCLAMATION QUESTION MARK}: Fumble scoreboard\n"
            )
        stats_len = len(humanize_number(entries[0][1][self._stat])) + 3
        start_position = (menu.current_page * self.per_page) + 1
        pos_len = len(str(start_position + 9)) + 2
        stats_plural = self._stat if self._stat.endswith("s") else f"{self._stat}s"
        stats_len = (len(stats_plural) if len(stats_plural) > stats_len else stats_len) + 2
        rebirth_len = len("Rebirths") + 2
        header = f"{'#':{pos_len}}{stats_plural.title().ljust(stats_len)}{'Rebirths':{rebirth_len}}{'Adventurer':2}"
        author = ctx.author

        if getattr(ctx, "guild", None):
            guild = ctx.guild
        else:
            guild = None

        players = []
        for position, (user_id, account_data) in enumerate(entries, start=start_position):
            if guild is not None:
                member = guild.get_member(user_id)
            else:
                member = None

            if member is not None:
                username = member.display_name
            else:
                user = menu.ctx.bot.get_user(user_id)
                if user is None:
                    username = user_id
                else:
                    username = user.name
            username = escape(str(username), formatting=True)
            if user_id == author.id:
                # Highlight the author's position
                username = f"<<{username}>>"

            pos_str = position
            rebirths = humanize_number(account_data["rebirths"])
            stats_value = humanize_number(account_data[self._stat.lower()])

            data = f"{f'{pos_str}.':{pos_len}}" f"{stats_value:{stats_len}}" f"{rebirths:{rebirth_len}}" f"{username}"
            players.append(data)

        embed = discord.Embed(
            title=f"Adventure {self._stat.title()} Scoreboard",
            color=await menu.ctx.embed_color(),
            description="```md\n{}``` ```md\n{}```".format(
                header,
                "\n".join(players),
            ),
        )
        embed.set_footer(text=f"Page {menu.current_page + 1}/{self.get_max_pages()}")
        return embed


class NVScoreboardSource(WeeklyScoreboardSource):
    def __init__(self, entries: List[Tuple[int, Dict]], stat: Optional[str] = None):
        super().__init__(entries)

    def is_paginating(self):
        return True

    async def format_page(self, menu: menus.MenuPages, entries: List[Tuple[int, Dict]]):
        ctx = menu.ctx
        loses_len = max(len(humanize_number(entries[0][1]["loses"])) + 3, 8)
        win_len = max(len(humanize_number(entries[0][1]["wins"])) + 3, 6)
        xp__len = max(len(humanize_number(entries[0][1]["xp__earnings"])) + 3, 8)
        gold__len = max(len(humanize_number(entries[0][1]["gold__losses"])) + 3, 12)
        start_position = (menu.current_page * self.per_page) + 1
        pos_len = len(str(start_position + 9)) + 2
        header = (
            f"{'#':{pos_len}}{'Wins':{win_len}}"
            f"{'Losses':{loses_len}}{'XP Won':{xp__len}}{'Gold Spent':{gold__len}}{'Adventurer':2}"
        )

        author = ctx.author

        if getattr(ctx, "guild", None):
            guild = ctx.guild
        else:
            guild = None

        players = []
        for position, (user_id, account_data) in enumerate(entries, start=start_position):
            if guild is not None:
                member = guild.get_member(user_id)
            else:
                member = None

            if member is not None:
                username = member.display_name
            else:
                user = menu.ctx.bot.get_user(user_id)
                if user is None:
                    username = user_id
                else:
                    username = user.name

            username = escape(str(username), formatting=True)
            if user_id == author.id:
                # Highlight the author's position
                username = f"<<{username}>>"

            pos_str = position
            loses = humanize_number(account_data["loses"])
            wins = humanize_number(account_data["wins"])
            xp__earnings = humanize_number(account_data["xp__earnings"])
            gold__losses = humanize_number(account_data["gold__losses"])

            data = (
                f"{f'{pos_str}.':{pos_len}} "
                f"{wins:{win_len}} "
                f"{loses:{loses_len}} "
                f"{xp__earnings:{xp__len}} "
                f"{gold__losses:{gold__len}} "
                f"{username}"
            )
            players.append(data)
        msg = "Adventure Negaverse Scoreboard\n```md\n{}``` ```md\n{}``````md\n{}```".format(
            header, "\n".join(players), f"Page {menu.current_page + 1}/{self.get_max_pages()}"
        )
        return msg


class SimpleSource(menus.ListPageSource):
    def __init__(self, entries: List[str, discord.Embed]):
        super().__init__(entries, per_page=1)

    def is_paginating(self):
        return True

    async def format_page(self, menu: menus.MenuPages, page: Union[str, discord.Embed]):
        return page


class EconomySource(menus.ListPageSource):
    def __init__(self, entries: List[Tuple[str, Dict[str, Any]]]):
        super().__init__(entries, per_page=10)
        self._total_balance_unified = None
        self._total_balance_sep = None
        self.author_position = None

    def is_paginating(self):
        return True

    async def format_page(self, menu: menus.MenuPages, entries: List[Tuple[str, Dict[str, Any]]]) -> discord.Embed:
        guild = menu.ctx.guild
        author = menu.ctx.author
        position = (menu.current_page * self.per_page) + 1
        bal_len = len(humanize_number(entries[0][1]["balance"]))
        pound_len = len(str(position + 9))
        user_bal = await bank.get_balance(menu.ctx.author, _forced=not menu.ctx.cog._separate_economy)
        if self.author_position is None:
            self.author_position = await bank.get_leaderboard_position(menu.ctx.author)
        header_primary = "{pound:{pound_len}}{score:{bal_len}}{name:2}\n".format(
            pound="#",
            name=_("Name"),
            score=_("Score"),
            bal_len=bal_len + 6,
            pound_len=pound_len + 3,
        )
        header = ""
        if menu.ctx.cog._separate_economy:
            if self._total_balance_sep is None:
                accounts = await bank._config.all_users()
                overall = 0
                for key, value in accounts.items():
                    overall += value["balance"]
                self._total_balance_sep = overall
            _total_balance = self._total_balance_sep
        else:
            if self._total_balance_unified is None:
                accounts = await bank._get_config(_forced=True).all_users()
                overall = 0
                for key, value in accounts.items():
                    overall += value["balance"]
                self._total_balance_unified = overall
            _total_balance = self._total_balance_unified
        percent = round((int(user_bal) / _total_balance * 100), 3)
        for position, acc in enumerate(entries, start=position):
            user_id = acc[0]
            account_data = acc[1]
            balance = account_data["balance"]
            if guild is not None:
                member = guild.get_member(user_id)
            else:
                member = None
            if member is not None:
                username = member.display_name
            else:
                user = menu.ctx.bot.get_user(user_id)
                if user is None:
                    username = f"{user_id}"
                else:
                    username = user.name
            username = escape(username, formatting=True)
            balance = humanize_number(balance)

            if acc[0] != author.id:
                header += f"{f'{humanize_number(position)}.': <{pound_len + 2}} {balance: <{bal_len + 5}} {username}\n"
            else:
                header += (
                    f"{f'{humanize_number(position)}.': <{pound_len + 2}} "
                    f"{balance: <{bal_len + 5}} "
                    f"<<{username}>>\n"
                )
        if self.author_position is not None:
            embed = discord.Embed(
                title="Adventure Economy Leaderboard\nYou are currently # {}/{}".format(
                    self.author_position, len(self.entries)
                ),
                color=await menu.ctx.embed_color(),
                description="```md\n{}``` ```md\n{}``` ```py\nTotal bank amount {}\nYou have {}% of the total amount!```".format(
                    header_primary, header, humanize_number(_total_balance), percent
                ),
            )
        else:
            embed = discord.Embed(
                title="Adventure Economy Leaderboard\n",
                color=await menu.ctx.embed_color(),
                description="```md\n{}``` ```md\n{}``` ```py\nTotal bank amount {}\nYou have {}% of the total amount!```".format(
                    header_primary, header, humanize_number(_total_balance), percent
                ),
            )
        embed.set_footer(text=f"Page {menu.current_page + 1}/{self.get_max_pages()}")

        return embed


class BaseBackpackSource(menus.ListPageSource):
    def __init__(self, entries: List[Dict], per_page=10):
        super().__init__(entries, per_page=per_page)
        self.col_name_len = 64
        self.col_slot_len = 10
        self.col_attr_len = 6
        self.col_rar_len = 12

    def is_paginating(self):
        return True

    def build_item_headers(self, exclude_cols=None):
        if exclude_cols is None:
            exclude_cols = []
        header = f"{self.format_ansi('Name'):{self.col_name_len}}"  # use ansi on this field to match spacing on table
        if "Rarity" not in exclude_cols:
            header += f"{'Rarity':{self.col_rar_len}}"
        header += f"{'Slot':{self.col_slot_len}}"

        for col in ['ATT', 'CHA', 'INT', 'DEX', 'LUK', 'QTY', 'DEG', 'LVL']:
            if col not in exclude_cols:
                if col == 'LVL':
                    header += f"{self.format_ansi(col):{self.col_attr_len + 8}}"
                else:
                    header += f"{col:{self.col_attr_len}}"
        return header

    def build_item_data(self, entries: List[Dict], start_position=0, exclude_cols=None):
        if not exclude_cols:
            exclude_cols = []
        data = []
        for (i, item) in enumerate(entries, start=start_position):
            name = item["name"]
            slot = "2-Hand" if item["slot"] == "Two Handed" or item["slot"] == Slot.two_handed else item["slot"]
            _set = item["set"]
            rarity = item["rarity"]
            cannot_equip = item["cannot_equip"]

            rarity_ansi = rarity.rarity_colour.value
            ansi_name = self.format_ansi(name, rarity_ansi)
            i_data = f"{ansi_name:{self.col_name_len}}"
            if "rarity" not in exclude_cols:
                i_data += f"{rarity:{self.col_rar_len}}"
            i_data += f"{slot:{self.col_slot_len}}"

            for col in ["att", "cha", "int", "dex", "luck", "owned", "degrade", "lvl"]:
                if col not in exclude_cols:
                    value = item.get(col, 0)
                    col_len = self.col_attr_len
                    if col == "degrade":
                        value = value if rarity in [Rarities.legendary, Rarities.event,
                                                    Rarities.ascended] and value >= 0 else ""
                    elif col == "lvl":
                        value = self.format_ansi(value, ANSITextColours.red) if cannot_equip else self.format_ansi(
                            value)
                        col_len += 8
                    i_data += f"{str(value):{col_len}}"
            if _set and rarity == Rarities.set and 'set' not in exclude_cols:
                data.append(_set)
            data.append(i_data)
        return data

    @staticmethod
    def format_ansi(text, ansi_code=ANSITextColours.white):
        return f"{ANSI_ESCAPE}[{ansi_code}m{text}{ANSI_CLOSE}"

    @staticmethod
    def wrap_ansi(msg):
        return "```ansi\n{}```".format(msg)

    @staticmethod
    def wrap_md(msg):
        return "```md\n{}```".format(msg)

    @staticmethod
    def wrap_ini(msg):
        return "```ini\n{}```".format(msg)


class PrettyBackpackSource(BaseBackpackSource):
    def __init__(self, entries: List[Dict], balance=0, backpack_size_cur=0, backpack_size_max=0,
                 body_msg="", contextual_msg=""):
        super().__init__(entries, per_page=10)
        self.balance = balance
        self.backpack_size_cur = backpack_size_cur
        self.backpack_size_max = backpack_size_max
        self.body_msg = body_msg
        self.contextual_msg = contextual_msg

    def build_balance_msg(self, menu: menus.MenuPages):
        return "```{}'s Backpack: {}/{} - {} gold```".format(menu.ctx.author.display_name,
                                                             humanize_number(self.backpack_size_cur),
                                                             humanize_number(self.backpack_size_max),
                                                             humanize_number(self.balance),
                                                             )

    async def format_page(self, menu: menus.MenuPages, entries: List[Dict]):
        start_position = (menu.current_page * self.per_page) + 1

        header = self.build_item_headers()
        data = self.build_item_data(entries, start_position)

        msg = self.build_balance_msg(menu)
        msg += self.wrap_ansi(header)

        if self.body_msg != "":
            msg += self.wrap_ansi(self.body_msg)
        elif len(data) == 0:
            msg += self.wrap_md("There doesn't seem to be anything here...")
        else:
            msg += self.wrap_ansi("\n".join(data))
            msg += self.wrap_ansi(f"Page {menu.current_page + 1}/{self.get_max_pages()}")

        if self.contextual_msg != "":
            msg += self.wrap_ansi(self.format_ansi("* ", ANSITextColours.yellow) + self.contextual_msg)

        return msg


class PrettySetInfoSource(BaseBackpackSource):
    def __init__(self, entries: List[Dict], set_name=None, character_set_count=-1):
        super().__init__(entries, per_page=1)
        self._character_set_count = character_set_count
        self._set_name = set_name
        self.col_name_len = 45  # override the name col len in parent class
        self.col_attr_len = 10
        self.col_set_len = 50

    def build_intro(self, menu: menus.MenuPages):
        msg = "{}'s Set Info".format(menu.ctx.author.display_name)
        if menu.current_page == 0:
            msg += ": Currently Equipped"
        else:
            msg += ": {}".format(self.format_ansi(self._set_name, ANSITextColours.red))
        return msg

    def build_set_info_header(self, name="Set Bonus", name_col_len=None):
        if not name_col_len:
            name_col_len = self.col_set_len
        header = (
            f"{self.format_ansi(name):{name_col_len}}"  # use ansi on this field to match spacing on table
            f"{'ATT':{self.col_attr_len}}"
            f"{'CHA':{self.col_attr_len}}"
            f"{'INT':{self.col_attr_len}}"
            f"{'DEX':{self.col_attr_len}}"
            f"{'LUK':{self.col_attr_len}}"
            f"{'Stats':{self.col_attr_len}}"
            f"{'EXP':{self.col_attr_len}}"
            f"{'Gold':{self.col_attr_len}}"
        )
        return header

    def format_data(self, bonus):
        att = bonus["att"]
        cha = bonus["cha"]
        _int = bonus["int"]
        dex = bonus["dex"]
        luk = bonus["luck"]
        stats = self.format_mult(bonus["statmult"])
        exp = self.format_mult(bonus["xpmult"])
        cp = self.format_mult(bonus["cpmult"])

        bonus_data = (
            f"{self.format_stat(att):{self.col_attr_len}}"
            f"{self.format_stat(cha):{self.col_attr_len}}"
            f"{self.format_stat(_int):{self.col_attr_len}}"
            f"{self.format_stat(dex):{self.col_attr_len}}"
            f"{self.format_stat(luk):{self.col_attr_len}}"
            f"{str(stats):{self.col_attr_len}}"
            f"{str(exp):{self.col_attr_len}}"
            f"{str(cp):{self.col_attr_len}}"
        )
        return bonus_data

    def format_char_set_data(self, set_name, bonus):
        parts = bonus["parts"]
        name = "{} ({})".format(self.format_ansi(set_name, ANSITextColours.red), parts)
        set_data = (
            f"{str(name):{self.col_set_len}}"
            f"{self.format_data(bonus)}"
        )
        return set_data

    def format_set_bonus_data(self, bonus, include_owned=True, name_col_len=None):
        if not name_col_len:
            name_col_len = self.col_set_len
        parts = bonus["parts"]
        parts_pieces = "Pieces: {}".format(str(parts))
        if include_owned and self._character_set_count >= parts:
            parts_pieces = self.format_ansi(parts_pieces, ANSITextColours.cyan)
        else:
            parts_pieces = self.format_ansi(parts_pieces, ANSITextColours.white)
        bonus_data = (
            f"{str(parts_pieces):{name_col_len}}"
            f"{self.format_data(bonus)}"
        )
        return bonus_data

    def build_char_set_data_block(self, entry):
        data = []
        for _set, bonus in entry.items():
            data.append(self.format_char_set_data(_set, bonus))
        data_str = "\n".join(data)

        if len(data) == 0:
            msg = self.wrap_md("No active set bonuses.")
        else:
            total = self.gather_total_amount(entry.values())
            total_str = self.format_set_bonus_data(total).replace("Pieces: 100", "Total      ")
            msg = self.wrap_ansi(data_str + "\n\n" + total_str)
        return msg

    def build_set_entry_data(self, entry, include_owned=True):
        data = []
        for bonus in entry:
            data.append(self.format_set_bonus_data(bonus, include_owned))
        data_str = "\n".join(data)
        total = self.gather_total_amount(entry)
        total_str = self.format_set_bonus_data(total).replace("Pieces: 100", "Total      ")
        return data_str, total_str

    def build_set_entry_block(self, entry, include_owned=True):
        data_str, total_str = self.build_set_entry_data(entry, include_owned)
        msg = self.wrap_ansi(data_str + "\n\n" + total_str)

        if include_owned:
            owned = self.gather_total_amount(entry, self._character_set_count)
            owned_str = self.format_set_bonus_data(owned).replace("Pieces:", "Owned: ")
            msg += self.wrap_ansi(owned_str)

        return msg

    async def format_page(self, menu: menus.MenuPages, entry):
        position = menu.current_page
        msg = self.wrap_ansi(self.build_intro(menu))

        if position == 0:
            # first page is currently equipped items
            msg += self.wrap_ansi(self.build_set_info_header())
            msg += self.build_char_set_data_block(entry)
        elif position == 1:
            # 2nd page is set items
            items = entry[:-1]
            data = self.build_item_data(items, exclude_cols=['rarity', 'degrade', 'set'])
            data_str = "\n".join(data)
            msg += self.wrap_ansi(self.build_item_headers(exclude_cols=['Rarity', 'DEG']))
            msg += self.wrap_ansi(data_str)

            owned_bonuses = entry[-1]
            owned_bonuses["parts"] = self._character_set_count
            msg_body = self.build_set_info_header("Total Equipable Bonus", (self.col_set_len - 5))
            msg_body += "\n" + self.format_set_bonus_data(owned_bonuses, True, (self.col_set_len - 5))
            msg += self.wrap_ansi(msg_body)
        else:
            # part upgrades
            msg += self.wrap_ansi(self.build_set_info_header(name="Set Bonus Upgrades"))
            for k, v in entry.items():
                data_str, total_str = self.build_set_entry_data(v, include_owned=False)
                msg_body = "{}\n\n".format(self.format_ansi('QTY ' + str(k), ANSITextColours.yellow))
                msg_body += data_str + "\n\n" + total_str
                msg += self.wrap_ansi(msg_body)
        footer = f"Page {menu.current_page + 1}/{self.get_max_pages()}"
        msg += self.wrap_ansi(footer)
        return msg

    @staticmethod
    def format_mult(value):
        mult = round((value - 1) * 100)
        return f"+{mult}%" if mult > 0 else f"{mult}%"

    @staticmethod
    def format_stat(value):
        if value > 0:
            return "+{}".format(value)
        else:
            return str(value)

    @staticmethod
    def gather_total_amount(bonuses, parts_limit=100):
        total = {"parts": 0, "att": 0, "cha": 0, "int": 0, "dex": 0, "luck": 0, "statmult": 1.0, "xpmult": 1.0, "cpmult": 1.0}
        for bonus in bonuses:
            parts = bonus["parts"]
            if parts_limit >= parts:
                total["parts"] = parts_limit
                total["att"] += bonus["att"]
                total["cha"] += bonus["cha"]
                total["int"] += bonus["int"]
                total["dex"] += bonus["dex"]
                total["luck"] += bonus["luck"]
                total["statmult"] += (bonus["statmult"] - 1)
                total["xpmult"] += (bonus["xpmult"] - 1)
                total["cpmult"] += (bonus["cpmult"] - 1)
        if total["parts"] == 0 and parts_limit != 100:
            total["parts"] = parts_limit
        return total


class StopButton(discord.ui.Button):
    def __init__(
            self,
            style: discord.ButtonStyle,
            row: Optional[int] = None,
    ):
        super().__init__(style=style, row=row)
        self.style = style
        self.emoji = "\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}"

    async def callback(self, interaction: discord.Interaction):
        self.view.stop()
        if interaction.message.flags.ephemeral:
            await interaction.response.edit_message(view=None)
            return
        await interaction.message.delete()


class _NavigateButton(discord.ui.Button):
    def __init__(self, style: discord.ButtonStyle, emoji: Union[str, discord.PartialEmoji], direction: int):
        super().__init__(style=style, emoji=emoji)
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        if self.direction == 0:
            self.view.current_page = 0
        elif self.direction == self.view.source.get_max_pages():
            self.view.current_page = self.view.source.get_max_pages() - 1
        else:
            self.view.current_page += self.direction
        try:
            page = await self.view.source.get_page(self.view.current_page)
        except IndexError:
            self.view.current_page = 0
            page = await self.view.source.get_page(self.view.current_page)
        kwargs = await self.view._get_kwargs_from_page(page)
        await interaction.response.edit_message(**kwargs)


class BaseMenu(discord.ui.View):
    def __init__(
            self,
            source: menus.PageSource,
            clear_reactions_after: bool = True,
            delete_message_after: bool = False,
            timeout: int = 180,
            message: discord.Message = None,
            **kwargs: Any,
    ) -> None:
        super().__init__(timeout=timeout)
        self._source = source
        self.page_start = kwargs.get("page_start", 0)
        self.current_page = self.page_start
        self.message = message
        self.forward_button = _NavigateButton(
            discord.ButtonStyle.grey,
            "\N{BLACK RIGHT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}",
            direction=1,
        )
        self.backward_button = _NavigateButton(
            discord.ButtonStyle.grey,
            "\N{BLACK LEFT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}",
            direction=-1,
        )
        self.first_button = _NavigateButton(
            discord.ButtonStyle.grey,
            "\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\N{VARIATION SELECTOR-16}",
            direction=0,
        )
        self.last_button = _NavigateButton(
            discord.ButtonStyle.grey,
            "\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\N{VARIATION SELECTOR-16}",
            direction=self.source.get_max_pages(),
        )
        self.stop_button = StopButton(discord.ButtonStyle.red)
        self.add_item(self.stop_button)
        if self.source.is_paginating():
            self.add_item(self.first_button)
            self.add_item(self.backward_button)
            self.add_item(self.forward_button)
            self.add_item(self.last_button)

    async def on_timeout(self):
        if self.message is not None:
            await self.message.edit(view=None)

    @property
    def source(self):
        return self._source

    async def change_source(self, source: menus.PageSource, interaction: discord.Interaction):
        await self.change_source_to_page(source, interaction, page=0)

    async def change_source_to_page(self, source: menus.PageSource, interaction: discord.Interaction, page):
        self._source = source
        self.current_page = page
        if self.message is not None:
            await source._prepare_once()
            await self.show_page(page, interaction)

    async def update(self):
        """
        Define this here so that subclasses can utilize this hook
        and update the state of the view before sending.
        This is useful for modifying disabled buttons etc.

        This gets called after the page has been formatted.
        """
        pass

    async def start(
            self,
            ctx: Optional[commands.Context],
            *,
            wait=False,
            page: int = 0,
            interaction: Optional[discord.Interaction] = None,
    ):
        """
        Starts the interactive menu session.

        Parameters
        -----------
        ctx: :class:`Context`
            The invocation context to use.
        channel: :class:`discord.abc.Messageable`
            The messageable to send the message to. If not given
            then it defaults to the channel in the context.
        wait: :class:`bool`
            Whether to wait until the menu is completed before
            returning back to the caller.

        Raises
        -------
        MenuError
            An error happened when verifying permissions.
        discord.HTTPException
            Adding a reaction failed.
        """

        if ctx is not None:
            self.bot = ctx.bot
            self._author_id = ctx.author.id
        elif interaction is not None:
            self.bot = interaction.client
            self._author_id = interaction.user.id
        self.ctx = ctx
        msg = self.message
        if msg is None:
            self.message = await self.send_initial_message(ctx, page=page, interaction=interaction)
        if wait:
            return await self.wait()

    async def _get_kwargs_from_page(self, page: Any):
        value = await self.source.format_page(self, page)
        if isinstance(value, dict):
            value["view"] = self
            return value
        elif isinstance(value, str):
            return {"content": value, "embed": None, "view": self}
        elif isinstance(value, discord.Embed):
            return {"embed": value, "content": None, "view": self}
        return value

    async def show_page(self, page_number: int, interaction: discord.Interaction):
        page = await self.source.get_page(page_number)
        self.current_page = page_number
        kwargs = await self._get_kwargs_from_page(page)
        await self.update()
        await interaction.response.edit_message(**kwargs)

    async def send_initial_message(
            self, ctx: Optional[commands.Context], page: int = 0, interaction: Optional[discord.Interaction] = None
    ):
        """

        The default implementation of :meth:`Menu.send_initial_message`
        for the interactive pagination session.

        This implementation shows the first page of the source.
        """
        self.current_page = page
        page = await self._source.get_page(page)
        kwargs = await self._get_kwargs_from_page(page)
        await self.update()
        if ctx is None and interaction is not None:
            await interaction.response.send_message(**kwargs)
            return await interaction.original_response()
        else:
            return await ctx.send(**kwargs)

    async def show_checked_page(self, page_number: int, interaction: discord.Interaction) -> None:
        max_pages = self._source.get_max_pages()
        try:
            if max_pages is None:
                # If it doesn't give maximum pages, it cannot be checked
                await self.show_page(page_number, interaction)
            elif page_number >= max_pages:
                await self.show_page(0, interaction)
            elif page_number < 0:
                await self.show_page(max_pages - 1, interaction)
            elif max_pages > page_number >= 0:
                await self.show_page(page_number, interaction)
        except IndexError:
            # An error happened that can be handled, so ignore it.
            pass

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id not in (*interaction.client.owner_ids, self._author_id):
            await interaction.response.send_message(_("You are not authorized to interact with this."), ephemeral=True)
            return False
        return True


class ScoreBoardMenu(BaseMenu):
    def __init__(
            self,
            source: menus.PageSource,
            cog: Optional[commands.Cog] = None,
            clear_reactions_after: bool = True,
            delete_message_after: bool = False,
            timeout: int = 180,
            message: discord.Message = None,
            show_global: bool = False,
            current_scoreboard: str = "wins",
            **kwargs: Any,
    ) -> None:
        super().__init__(
            source=source,
            clear_reactions_after=clear_reactions_after,
            delete_message_after=delete_message_after,
            timeout=timeout,
            message=message,
            **kwargs,
        )
        self.cog = cog
        self.show_global = show_global
        self._current = current_scoreboard

    async def update(self):
        buttons = {
            "wins": self.wins,
            "loses": self.losses,
            "fight": self.physical,
            "spell": self.magic,
            "talk": self.diplomacy,
            "pray": self.praying,
            "run": self.runner,
            "fumbles": self.fumble,
        }
        for button in buttons.values():
            button.disabled = False
        buttons[self._current].disabled = True

    @discord.ui.button(
        label=_("Wins"),
        style=discord.ButtonStyle.grey,
        emoji="\N{FACE WITH PARTY HORN AND PARTY HAT}",
        row=1,
        disabled=True,
    )
    async def wins(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "wins":
            await interaction.response.defer()
            # this deferal is unnecessary now since the buttons are just disabled
            # however, in the event that the button gets passed and the state is not
            # as we expect at least try not to send the user an interaction failed message
            return
        self._current = "wins"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )

    @discord.ui.button(label=_("Losses"), style=discord.ButtonStyle.grey, emoji="\N{FIRE}", row=1)
    async def losses(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "loses":
            await interaction.response.defer()
            return
        self._current = "loses"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )

    @discord.ui.button(label=_("Physical"), style=discord.ButtonStyle.grey, emoji="\N{DAGGER KNIFE}", row=1)
    async def physical(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """stops the pagination session."""
        if self._current == "fight":
            await interaction.response.defer()
            return
        self._current = "fight"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )

    @discord.ui.button(label=_("Magic"), style=discord.ButtonStyle.grey, emoji="\N{SPARKLES}", row=1)
    async def magic(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "spell":
            await interaction.response.defer()
            return
        self._current = "spell"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )

    @discord.ui.button(label=_("Charisma"), style=discord.ButtonStyle.grey, emoji="\N{LEFT SPEECH BUBBLE}", row=1)
    async def diplomacy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "talk":
            await interaction.response.defer()
            return
        self._current = "talk"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )

    @discord.ui.button(label=_("Pray"), style=discord.ButtonStyle.grey, emoji="\N{PERSON WITH FOLDED HANDS}", row=2)
    async def praying(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "pray":
            await interaction.response.defer()
            return
        self._current = "pray"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )

    @discord.ui.button(label=_("Run"), style=discord.ButtonStyle.grey, emoji="\N{RUNNER}", row=2)
    async def runner(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "run":
            await interaction.response.defer()
            return
        self._current = "run"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )

    @discord.ui.button(label=_("Fumbles"), style=discord.ButtonStyle.grey, emoji="\N{EXCLAMATION QUESTION MARK}", row=2)
    async def fumble(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "fumbles":
            await interaction.response.defer()
            return
        self._current = "fumbles"
        rebirth_sorted = await self.cog.get_global_scoreboard(
            guild=self.ctx.guild if not self.show_global else None, keyword=self._current
        )
        await self.change_source(
            source=ScoreboardSource(entries=rebirth_sorted, stat=self._current), interaction=interaction
        )


class LeaderboardMenu(BaseMenu):
    def __init__(
            self,
            source: menus.PageSource,
            cog: Optional[commands.Cog] = None,
            clear_reactions_after: bool = True,
            delete_message_after: bool = False,
            timeout: int = 180,
            message: discord.Message = None,
            show_global: bool = False,
            current_scoreboard: str = "leaderboard",
            **kwargs: Any,
    ) -> None:
        super().__init__(
            source,
            clear_reactions_after=clear_reactions_after,
            delete_message_after=delete_message_after,
            timeout=timeout,
            message=message,
            **kwargs,
        )
        self.cog = cog
        self.show_global = show_global
        self._current = current_scoreboard

    async def update(self):
        buttons = {"leaderboard": self.home, "economy": self.economy}
        for button in buttons.values():
            button.disabled = False
        buttons[self._current].disabled = True

    def _unified_bank(self):
        return not self.cog._separate_economy

    @discord.ui.button(
        label=_("Leaderboard"),
        style=discord.ButtonStyle.grey,
        emoji="\N{CHART WITH UPWARDS TREND}",
        row=1,
        disabled=True,
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "leaderboard":
            await interaction.response.defer()
            return
        self._current = "leaderboard"
        rebirth_sorted = await self.cog.get_leaderboard(guild=self.ctx.guild if not self.show_global else None)
        await self.change_source(source=LeaderboardSource(entries=rebirth_sorted), interaction=interaction)

    @discord.ui.button(label=_("Economy"), style=discord.ButtonStyle.grey, emoji="\N{MONEY WITH WINGS}", row=1)
    async def economy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current == "economy":
            await interaction.response.defer()
            return
        self._current = "economy"
        bank_sorted = await bank.get_leaderboard(
            guild=self.ctx.guild if not self.show_global else None, _forced=self._unified_bank()
        )
        await self.change_source(source=EconomySource(entries=bank_sorted), interaction=interaction)


class BackpackSelectEquip(discord.ui.Select):
    def __init__(self, options: List[discord.SelectOption], placeholder: str, max_values: Optional[int] = None):
        self.view: BackpackMenu
        super().__init__(min_values=1, max_values=max_values or len(options), options=options, placeholder=placeholder)
        self.selected_items = []

    async def equip_items(self, interaction: discord.Interaction):
        if self.view.cog.in_adventure(self.view.ctx):
            return await smart_embed(
                message=_("You tried to equip an item but the monster ahead of you commands your attention."),
                ephemeral=True,
                interaction=interaction,
            )
        equip_msg = ""
        await interaction.response.defer()
        async with self.view.cog.get_lock(self.view.ctx.author):
            for item_index in self.values:
                equip_item = self.view.source.current_table.items[int(item_index)]
                try:
                    c = await Character.from_json(
                        self.view.ctx, self.view.cog.config, self.view.ctx.author, self.view.cog._daily_bonus
                    )
                except Exception as exc:
                    log.exception("Error with the new character sheet", exc_info=exc)
                    return
                equiplevel = c.equip_level(equip_item)
                if is_dev(self.view.ctx.author):  # FIXME:
                    equiplevel = 0

                if not c.can_equip(equip_item):
                    equip_msg += _("You need to be level `{level}` to equip {item}.").format(
                        level=equiplevel, item=equip_item.ansi
                    )
                    equip_msg += "\n\n"
                    continue

                equip = c.backpack.get(equip_item.name)
                if equip:
                    slot = equip.slot
                    put = getattr(c, equip.slot.char_slot)
                    equip_msg += _("{author} equipped {item} ({slot} slot)").format(
                        author=escape(self.view.ctx.author.display_name),
                        item=equip.as_ansi(),
                        slot=slot.get_name(),
                    )
                    if put:
                        equip_msg += " " + _("and put {put} into their backpack").format(
                            author=escape(self.view.ctx.author.display_name),
                            item=equip.as_ansi(),
                            slot=slot,
                            put=getattr(c, equip.slot.char_slot).as_ansi(),
                        )
                    c = await c.equip_item(equip, True, is_dev(self.view.ctx.author))  # FIXME:
                    await self.view.cog.config.user(self.view.ctx.author).set(
                        await c.to_json(self.view.ctx, self.view.cog.config)
                    )
                equip_msg += ".\n\n"
        await smart_embed(message=box(equip_msg, lang="ansi"), interaction=interaction)

    async def forge_items(self, interaction: discord.Interaction):
        for item_index in self.values:
            item = self.view.source.current_table.items[int(item_index)]
            if item in self.view.selected_items and item.owned < 2:
                return await smart_embed(
                    message=_("You can't make items out of thin air like that! This is a duplicate."),
                    interaction=interaction,
                    ephemeral=True,
                )
            self.view.selected_items.append(item)
        page = await self.view.source.get_page(self.view.current_page)
        kwargs = await self.view._get_kwargs_from_page(page)
        await interaction.response.edit_message(**kwargs)
        if len(self.view.selected_items) >= 2:
            self.view.stop()

    async def callback(self, interaction: discord.Interaction):
        if self.view.tinker_forge:
            return await self.forge_items(interaction)
        await self.equip_items(interaction)


class BackpackSource(menus.ListPageSource):
    def __init__(self, entries: List[BackpackTable]):
        super().__init__(entries, per_page=1)
        self.current_table = entries[0]
        self.select_options = [
            discord.SelectOption(label=str(item), value=i, description=item.stat_str(), emoji=item.rarity.emoji)
            for i, item in enumerate(self.current_table.items)
        ]

    def is_paginating(self):
        return True

    async def format_page(self, view: BackpackMenu, page: BackpackTable):
        self.current_table = page
        self.select_options = [
            discord.SelectOption(label=str(item), value=i, description=item.stat_str(), emoji=item.rarity.emoji)
            for i, item in enumerate(self.current_table.items)
        ]
        ret = str(page)

        if view.tinker_forge and view.selected_items:
            items = view.selected_items
            ret += box(_("Selected Items:\n{items}").format(items="\n".join([i.as_ansi() for i in items])), lang="ansi")
        return ret



class BackpackMenu(BaseMenu):
    def __init__(
            self,
            source: BackpackSource,
            help_command: commands.Command,
            cog: AdventureMixin,
            clear_reactions_after: bool = True,
            delete_message_after: bool = False,
            timeout: int = 180,
            message: discord.Message = None,
            tinker_forge: bool = False,
            **kwargs: Any,
    ) -> None:
        super().__init__(
            source,
            clear_reactions_after=clear_reactions_after,
            delete_message_after=delete_message_after,
            timeout=timeout,
            message=message,
            **kwargs,
        )
        self.__help_command = help_command
        self.equip_select = None
        self.tinker_forge = tinker_forge

        self.cog = cog
        self.selected_items = []

    def _modify_select(self):
        if self.equip_select is not None:
            self.remove_item(self.equip_select)
        if getattr(self.source, "select_options", None):
            max_values = 1 if self.tinker_forge else None
            placeholder = _("Forge") if self.tinker_forge else _("Equip")
            self.equip_select = BackpackSelectEquip(self.source.select_options, placeholder, max_values)
            self.add_item(self.equip_select)

    async def _get_kwargs_from_page(self, page: Any):
        ret = await super()._get_kwargs_from_page(page)
        self._modify_select()
        return ret

    @discord.ui.button(style=discord.ButtonStyle.grey, emoji="\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16}", row=1)
    async def send_help(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Sends help for the provided command."""
        await interaction.response.defer()
        await self.ctx.send_help(self.__help_command)


class InteractiveBackpackMenu(BaseMenu):
    def __init__(
            self,
            source,
            character_supplier: Any,
            character: Character,
            sell_callback: Any,
            convert_callback: Any,
            open_loot_callback: Any,
            auto_toggle_callback: Any,
            clear_reactions_after: bool = True,
            delete_message_after: bool = False,
            timeout: int = 180,
            message: discord.Message = None,
            **kwargs: Any
    ) -> None:
        super().__init__(
            source=source,
            clear_reactions_after=clear_reactions_after,
            delete_message_after=delete_message_after,
            timeout=timeout,
            message=message,
            **kwargs
        )
        self._character_supplier = character_supplier
        self._c = character
        self._sell_callback = sell_callback
        self._convert_callback = convert_callback
        self._open_loot_callback = open_loot_callback
        self._auto_toggle_callback = auto_toggle_callback
        self._current_view = "default"
        self._rarities = [i for i in Rarities]
        self._stats = self.initial_stats_filters()
        self._equippable = False
        self._delta = False
        self._sold_count = 0
        self._search_name_text = ""
        self._search_slots_text = ""
        self._search_set_text = ""
        self._viewing_set_name = ""
        self._set_selections = None
        # remove useless buttons from parents
        self.remove_item(self.stop_button)
        self.remove_item(self.last_button)
        self.remove_item(self.first_button)
        self.remove_item(self.forward_button)
        self.remove_item(self.backward_button)

    async def initial_state(self):
        self._c = await self._character_supplier(self.ctx)
        await self.set_backpack_view_buttons()  # try to remove sets buttons, must be done before setting current_view
        self._current_view = "default"
        self._rarities = [i for i in Rarities]
        self._stats = self.initial_stats_filters()
        self._equippable = False
        self._delta = False
        self._sold_count = 0
        self._search_name_text = ""
        self._search_slots_text = ""
        self._search_set_text = ""
        self._viewing_set_name = ""

    @staticmethod
    def initial_stats_filters():
        return {
            'att': None,
            'cha': None,
            'int': None,
            'dex': None,
            'luk': None,
            'deg': None,
            'lvl': None
        }

    def highlight_stats_filter_button(self, button, attrs):
        if self._current_view == "loot":
            button.style = discord.ButtonStyle.grey
            button.disabled = True
            return False
        else:
            button.disabled = False
            selected = False
            for i in attrs:
                if self._stats[i] is not None:
                    button.style = discord.ButtonStyle.green
                    selected = True
                    break
            if not selected:
                button.style = discord.ButtonStyle.grey
            return selected

    async def update(self):
        view_buttons = {
            "default": self.default_button,
            "can_equip": self.can_equip_button,
            "loot": self.loot_button,
            "sets": self.sets_button
        }
        for button in view_buttons.values():
            button.disabled = False
        view_buttons[self._current_view].disabled = True
        loot_view = self._current_view == "loot"

        rarity_buttons = {
            Rarities.rare: self.rare_filter,
            Rarities.epic: self.epic_filter,
            Rarities.legendary: self.legendary_filter,
            Rarities.ascended: self.ascended_filter,
            Rarities.set: self.set_filter
        }

        rarity_enabled = False
        for r in [Rarities.rare, Rarities.epic, Rarities.legendary, Rarities.ascended, Rarities.set]:
            if loot_view:
                if self._c.treasure[r.value] > 0:
                    rarity_buttons[r].style = discord.ButtonStyle.green
                    rarity_buttons[r].disabled = False
                else:
                    rarity_buttons[r].style = discord.ButtonStyle.grey
                    rarity_buttons[r].disabled = True
            else:
                rarity_buttons[r].disabled = False
                if r in self._rarities:
                    rarity_buttons[r].style = discord.ButtonStyle.green
                    rarity_enabled = True
                else:
                    rarity_buttons[r].style = discord.ButtonStyle.grey

        if not rarity_enabled or loot_view:
            self.clear_rarity.disabled = True
            self.clear_rarity.style = discord.ButtonStyle.grey
        else:
            self.clear_rarity.disabled = False
            self.clear_rarity.style = discord.ButtonStyle.red

        filter_selected = self.highlight_stats_filter_button(self.filter_group_1, ['att', 'cha', 'int', 'dex', 'luk'])
        filter_selected = self.highlight_stats_filter_button(self.filter_group_2, ['deg', 'lvl']) or filter_selected
        if (len(self._search_name_text) > 0 or len(self._search_set_text) > 0 or len(self._search_slots_text) > 0) and not loot_view:
            self.search_button.style = discord.ButtonStyle.green
            filter_selected = True
        else:
            self.search_button.style = discord.ButtonStyle.grey
        self.search_button.disabled = loot_view

        if not filter_selected or loot_view:
            self.clear_filters.disabled = True
            self.clear_filters.style = discord.ButtonStyle.grey
        else:
            self.clear_filters.disabled = False
            self.clear_filters.style = discord.ButtonStyle.red

        if self._c.do_not_disturb:
            self.auto_toggle.label = "Turn Auto-Battle On \u200b"
            self.auto_toggle.style = discord.ButtonStyle.red
        else:
            self.auto_toggle.label = "Turn Auto-Battle Off"
            self.auto_toggle.style = discord.ButtonStyle.green

        self.update_contextual_button()

    async def get_set_selections(self):
        if self._set_selections is None:
            sets = await self._c.get_set_count()
            self._set_selections = InteractiveSetSelect(self, self.ctx, sets, row=3)
        return self._set_selections

    def remove_rarity_row(self):
        self.remove_item(self.rare_filter)
        self.remove_item(self.epic_filter)
        self.remove_item(self.legendary_filter)
        self.remove_item(self.ascended_filter)
        self.remove_item(self.set_filter)

    def remove_filters_row(self):
        self.remove_item(self.search_button)
        self.remove_item(self.filter_group_1)
        self.remove_item(self.filter_group_2)
        self.remove_item(self.clear_rarity)
        self.remove_item(self.clear_filters)

    def add_rarity_row(self):
        self.add_item(self.rare_filter)
        self.add_item(self.epic_filter)
        self.add_item(self.legendary_filter)
        self.add_item(self.ascended_filter)
        self.add_item(self.set_filter)
        
    def add_filters_row(self):
        self.add_item(self.search_button)
        self.add_item(self.filter_group_1)
        self.add_item(self.filter_group_2)
        self.add_item(self.clear_rarity)
        self.add_item(self.clear_filters)

    async def set_backpack_view_buttons(self):
        self.reset_contextual_state()
        if self._current_view == "sets":
            self.remove_item(await self.get_set_selections())
            self.add_rarity_row()
            self.add_filters_row()

    async def set_setinfo_view_buttons(self):
        self.reset_contextual_state()
        self.remove_rarity_row()
        self.remove_filters_row()
        self.add_item(await self.get_set_selections())

    def update_contextual_button(self):
        label_space_pre = "\u200b "
        label_space_post = " \u200b"
        sell_all_label = str(label_space_pre * 7) + "Sell All" + str(label_space_post * 8)
        confirm_sell_label = str(label_space_pre * 6) + "Confirm Sell" + str(label_space_post * 6)
        auto_convert_label = str(label_space_pre * 5) + "Auto-Convert" + str(label_space_post * 4)
        go_to_backpack_label = "Show In Backpack"

        if self._current_view == "sets":
            self.contextual_button.emoji = None
            self.contextual_button.label = go_to_backpack_label
            self.contextual_button.style = discord.ButtonStyle.green
        elif self._current_view != "loot":
            if self._sold_count == SELL_CONFIRM_AMOUNT:
                # sell all confirm
                self.contextual_button.emoji = None
                self.contextual_button.label = confirm_sell_label
                self.contextual_button.style = discord.ButtonStyle.red
            else:
                # sell all enabled
                self.contextual_button.emoji = "\N{COIN}"
                self.contextual_button.label = sell_all_label
                self.contextual_button.style = discord.ButtonStyle.red
        else:
            self.contextual_button.emoji = None
            self.contextual_button.label = auto_convert_label
            self.contextual_button.style = discord.ButtonStyle.green

    @discord.ui.button(style=discord.ButtonStyle.red, emoji="\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}",
                       row=0)
    async def _stop_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        button.view.stop()
        if interaction.message.flags.ephemeral:
            await interaction.response.edit_message(view=None)
            return
        await interaction.message.delete()

    @discord.ui.button(style=discord.ButtonStyle.grey,
                       emoji="\N{BLACK LEFT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}", row=0)
    async def _back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        button.view.current_page -= 1 if button.view.current_page > 0 else 0
        await self.navigate_page(interaction, button)

    @discord.ui.button(style=discord.ButtonStyle.grey,
                       emoji="\N{BLACK RIGHT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}", row=0)
    async def _forward_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        max_pages = self.source.get_max_pages()
        if button.view.current_page + 1 < max_pages:
            button.view.current_page += 1
        await self.navigate_page(interaction, button)

    @discord.ui.button(style=discord.ButtonStyle.grey, label="Contextual Button", row=0)
    async def contextual_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current_view == "sets":
            set_name = self._viewing_set_name
            await self.initial_state()
            self._search_set_text = set_name
            await self.do_change_source(interaction=interaction)
        elif self._current_view != "loot":
            if self._sold_count == SELL_CONFIRM_AMOUNT:
                # confirm action
                backpack_items = await self.get_backpack_item_for_sell()
                c, msg = await self._sell_callback(self.ctx, self._c, backpack_items)
                self._c = c
                self._sold_count = 0
                await self.do_change_source(interaction=interaction, contextual_msg=msg)
            else:
                # start confirm action
                self._sold_count = SELL_CONFIRM_AMOUNT
                await self.do_change_source(interaction=interaction)
        else:
            # auto-convert button
            c, msg = await self._convert_callback(self.ctx, self._c)
            self._c = c
            await self.do_change_source(interaction, contextual_msg=msg)

    @discord.ui.button(style=discord.ButtonStyle.red, label="Auto Toggle", row=0)
    async def auto_toggle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._c = await self._auto_toggle_callback(self.ctx)
        if self._current_view == "sets":
            await self.do_change_source_to_sets(interaction)
        else:
            await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.primary,
                       label="\u200b \u200b \u200b \u200b \u200b \u200b \u200b \u200b Backpack\u200b \u200b \u200b \u200b \u200b \u200b \u200b \u200b",
                       row=1)
    async def default_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._equippable = False
        self._delta = False
        await self.set_backpack_view_buttons()
        self._current_view = "default"
        await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.primary,
                       label="Loot",
                       row=1)
    async def loot_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.set_backpack_view_buttons()
        self._current_view = "loot"
        await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.primary, label="\u200b \u200b Equipable \u200b \u200b \u200b", row=1)
    async def can_equip_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._equippable = True
        self._delta = True
        await self.set_backpack_view_buttons()
        self._current_view = "can_equip"
        await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.primary,
                       label="\u200b \u200b \u200b \u200b \u200b \u200b Sets \u200b \u200b \u200b \u200b \u200b",
                       row=1)
    async def sets_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.set_setinfo_view_buttons()
        self._current_view = "sets"
        await self.do_change_source_to_sets(interaction)

    @discord.ui.button(style=discord.ButtonStyle.red,
                       label="\u200b \u200b \u200b \u200b Reset \u200b \u200b \u200b \u200b ", row=1)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.initial_state()
        await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.green,
                       label="\u200b \u200b \u200b Normal + Rare \u200b \u200b \u200b ", row=2)
    async def rare_filter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current_view == "loot":
            title = "Can't open Normal, sorry. Enter # for Rare."
            modal = InteractiveBackpackLootModal(self, self.ctx, "rare", self._c.treasure["rare"].number, title)
            await interaction.response.send_modal(modal)
        else:
            self.update_rarities(Rarities.normal)
            self.update_rarities(Rarities.rare)
            await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.green, label="Epic", row=2)
    async def epic_filter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current_view == "loot":
            modal = InteractiveBackpackLootModal(self, self.ctx, "epic", self._c.treasure["epic"].number)
            await interaction.response.send_modal(modal)
        else:
            self.update_rarities(Rarities.epic)
            await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.green, label="\u200b \u200b Legendary \u200b \u200b", row=2)
    async def legendary_filter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current_view == "loot":
            modal = InteractiveBackpackLootModal(self, self.ctx, "legendary", self._c.treasure["legendary"].number)
            await interaction.response.send_modal(modal)
        else:
            self.update_rarities(Rarities.legendary)
            await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.green, label="Ascended", row=2)
    async def ascended_filter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current_view == "loot":
            modal = InteractiveBackpackLootModal(self, self.ctx, "ascended", self._c.treasure["ascended"].number)
            await interaction.response.send_modal(modal)
        else:
            self.update_rarities(Rarities.ascended)
            await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.green,
                       label="\u200b \u200b \u200b \u200b \u200b \u200b \u200b Set \u200b \u200b \u200b \u200b \u200b \u200b",
                       row=2)
    async def set_filter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._current_view == "loot":
            modal = InteractiveBackpackLootModal(self, self.ctx, "set", self._c.treasure["set"].number)
            await interaction.response.send_modal(modal)
        else:
            self.update_rarities(Rarities.set)
            await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.primary,
                       label="\u200b Search By Name \u200b",
                       row=3)
    async def search_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = InteractiveBackpackSearchModal(self, self.ctx)
        await interaction.response.send_modal(modal)

    @discord.ui.button(style=discord.ButtonStyle.grey,
                       label="Stats",
                       row=3)
    async def filter_group_1(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        input_mapping = {key: self._stats[key] for key in
                         sorted(self._stats.keys() & {'att', 'cha', 'int', 'dex', 'luk'})}
        modal = InteractiveBackpackFilterModal(self, self.ctx, "Stats Filters Group 1", input_mapping)
        await interaction.response.send_modal(modal)

    @discord.ui.button(style=discord.ButtonStyle.grey,
                       label="\u200b \u200b \u200b \u200b \u200b Deg/Lvl \u200b \u200b \u200b \u200b",
                       row=3)
    async def filter_group_2(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        input_mapping = {key: self._stats[key] for key in sorted(self._stats.keys() & {'deg', 'lvl'})}
        modal = InteractiveBackpackFilterModal(self, self.ctx, "Stats Filters Group 2", input_mapping)
        await interaction.response.send_modal(modal)

    @discord.ui.button(style=discord.ButtonStyle.red, emoji="\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}",
                       label="Rarity", row=3)
    async def clear_rarity(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._rarities = [Rarities.pet]  # cheat here and use a rarity we don't have to filter
        self.reset_contextual_state()
        await self.do_change_source(interaction)

    @discord.ui.button(style=discord.ButtonStyle.red, emoji="\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}",
                       label="Filters", row=3)
    async def clear_filters(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._stats = self.initial_stats_filters()
        self._search_name_text = ""
        self._search_slots_text = ""
        self._search_set_text = ""
        self.reset_contextual_state()
        await self.do_change_source(interaction)

    def update_rarities(self, rarity):
        self.reset_contextual_state()
        if rarity in self._rarities:
            self._rarities.remove(rarity)
        else:
            self._rarities.append(rarity)

    def reset_contextual_state(self):
        self._sold_count = 0

    async def get_backpack_item_for_sell(self):
        return await self.get_backpack_items(True)

    def get_filter_attr(self, attr):
        value = self._stats[attr]
        if value is not None:
            return process_argparse_stat(self._stats, attr)[attr]
        else:
            return None

    def set_stat_filter(self, attr, value):
        if value:
            self._stats[attr] = [value]
        else:
            self._stats[attr] = None

    def get_slots_filter(self):
        if self._search_slots_text:
            arr = self._search_slots_text
            arr = arr.lower()
            arr = arr.replace("2-handed", "two_handed")
            arr = arr.replace("two-handed", "two_handed")
            arr = arr.replace("2-hand", "two_handed")
            result = set()
            for s in arr.split(","):
                try:
                    slot = Slot.get_from_name(s.strip())
                    result.add(slot)
                except KeyError:
                    # ignore slots that were entered incorrectly
                    continue
            return list(result)
        else:
            return None

    async def get_backpack_items(self, for_sell=False):
        att_filter = self.get_filter_attr('att')
        cha_filter = self.get_filter_attr('cha')
        int_filter = self.get_filter_attr('int')
        dex_filter = self.get_filter_attr('dex')
        luk_filter = self.get_filter_attr('luk')
        deg_filter = self.get_filter_attr('deg')
        lvl_filter = self.get_filter_attr('lvl')

        if for_sell:
            return await self._c.get_argparse_backpack_no_format_items(rarities=self._rarities,
                                                                       slots=self.get_slots_filter(),
                                                                       equippable=self._equippable,
                                                                       delta=self._delta,
                                                                       match=self._search_name_text,
                                                                       strength=att_filter,
                                                                       charisma=cha_filter,
                                                                       intelligence=int_filter,
                                                                       dexterity=dex_filter,
                                                                       luck=luk_filter,
                                                                       degrade=deg_filter,
                                                                       level=lvl_filter,
                                                                       set=self._search_set_text)
        else:
            return await self._c.get_argparse_backpack_no_format(rarities=self._rarities,
                                                                 slots=self.get_slots_filter(),
                                                                 equippable=self._equippable,
                                                                 delta=self._delta,
                                                                 match=self._search_name_text,
                                                                 strength=att_filter,
                                                                 charisma=cha_filter,
                                                                 intelligence=int_filter,
                                                                 dexterity=dex_filter,
                                                                 luck=luk_filter,
                                                                 degrade=deg_filter,
                                                                 level=lvl_filter,
                                                                 set=self._search_set_text)

    async def do_change_source(self, interaction, items=None, contextual_msg=""):
        balance = self._c.bal
        backpack_items = await self.get_backpack_items() if items is None else items
        body_msg = ""

        if self._sold_count == SELL_CONFIRM_AMOUNT:
            contextual_msg = (
                "Are you sure you want to sell these {} listings and their copies? "
                "Press the confirm button to proceed."
            ).format(len(backpack_items))
            for (i, item) in enumerate(backpack_items):
                if item["rarity"] == Rarities.set:
                    contextual_msg += "\n\n! WARNING: You are about to sell a Set piece !"
                    break
        elif self._current_view == "loot":
            chests = "You own {} chests".format(self._c.treasure.ansi)
            if items is None:
                body_msg = chests
                body_msg += (
                    "\n"
                    "\nUse corresponding rarity buttons below to open your chests."
                    "\n"
                    "\nAuto-Convert will convert all your chests in multiples of 25 up to Legendary."
                )
            elif contextual_msg == "":
                contextual_msg = chests

        await self.change_source(
            source=PrettyBackpackSource(entries=backpack_items,
                                        balance=balance,
                                        backpack_size_cur=len(self._c.backpack),
                                        backpack_size_max=self._c.get_backpack_slots(),
                                        body_msg=body_msg,
                                        contextual_msg=contextual_msg),
            interaction=interaction)

    async def do_change_source_to_sets(self, interaction):
        self._c.get_set_bonus()
        source = PrettySetInfoSource(entries=[self._c.partial_sets])
        await self.change_source(source=source, interaction=interaction)

    def build_set_items(self, set_name):
        set_items = self._c.get_set_items(set_name)
        data = []
        for item in set_items:
            item_level = self._c.equip_level(item)
            cannot_equip = item_level > self._c.lvl
            if item.slot == Slot.two_handed:
                cannot_equip = item_level > self._c.lvl
                i_data = {"name": item.name, "slot": item.slot, "att": item.att * 2, "cha": item.cha * 2, "int": item.int * 2,
                          "dex": item.dex * 2, "luck": item.luck * 2, "owned": item.owned, "rarity": item.rarity, "set": item.set,
                          "lvl": item_level, "cannot_equip": cannot_equip}
            else:
                i_data = {"name": item.name, "slot": item.slot, "att": item.att, "cha": item.cha, "int": item.int,
                          "dex": item.dex, "luck": item.luck, "owned": item.owned, "rarity": item.rarity, "set": item.set,
                          "lvl": item_level, "cannot_equip": cannot_equip}
            data.append(i_data)
        return data

    async def do_change_setinfo_source(self, interaction, set_name):
        cog = self.ctx.bot.get_cog("Adventure")
        set_bonuses = cog.SET_BONUSES.get(set_name)
        set_upgrades = cog.SET_UPGRADES.get(set_name)

        set_items = self.build_set_items(set_name)
        owned_set_bonus = self._c.get_set_bonus_with_upgrades(set_name)
        set_items.append(owned_set_bonus)

        self._c.get_set_bonus()
        self._c.get_set_bonus_with_upgrades(set_name)
        set_upgrades_expanded = {1: set_bonuses}
        set_upgrades_expanded.update(self._c.build_set_bonus_upgrades(set_bonuses, set_upgrades))
        set_upgrades_1 = {key: set_upgrades_expanded[key] for key in
                          sorted(set_upgrades_expanded.keys() & {1, 3})}
        set_upgrades_2 = {key: set_upgrades_expanded[key] for key in
                          sorted(set_upgrades_expanded.keys() & {5, 10})}
        set_upgrades_3 = {20: set_upgrades_expanded[20]}
        entries = [self._c.partial_sets, set_items, set_upgrades_1, set_upgrades_2, set_upgrades_3]

        sets = await self._c.get_set_count()
        character_set_count = sets[set_name][1]
        self._viewing_set_name = set_name
        await self.change_source_to_page(source=PrettySetInfoSource(character_set_count=character_set_count,
                                                                    set_name=set_name,
                                                                    entries=entries),
                                         interaction=interaction,
                                         page=1)  # start at page 1 where set items are

    async def do_open_loot(self, interaction, rarity, number):
        c, opened_items, msg = await self._open_loot_callback(self.ctx, self._c, rarity, number)
        self._c = c
        await self.do_change_source(interaction, opened_items, contextual_msg=msg)

    @staticmethod
    async def navigate_page(interaction, button):
        try:
            page = await button.view.source.get_page(button.view.current_page)
        except IndexError:
            button.view.current_page = 0
            page = await button.view.source.get_page(button.view.current_page)
        kwargs = await button.view._get_kwargs_from_page(page)
        await interaction.response.edit_message(**kwargs)

    @property
    def search_name_text(self):
        return self._search_name_text

    @property
    def search_slots_text(self):
        return self._search_slots_text

    @property
    def search_set_text(self):
        return self._search_set_text


class InteractiveBackpackFilterModal(discord.ui.Modal):
    def __init__(self, backpack_menu: InteractiveBackpackMenu, ctx: commands.Context, title,
                 input_mapping: Dict[str, str]):
        super().__init__(title=title)
        self.ctx = ctx
        self.backpack_menu = backpack_menu
        self.keys = []
        self.build_inputs(input_mapping)

    def build_inputs(self, input_mapping):
        keys = []
        for (key, value) in input_mapping.items():
            built_input = self.build_input(key.upper(), value)
            item = {'value': value, 'input': built_input}
            self.__setattr__(key, item)
            keys.append(key)
            self.add_item(built_input)
        self.keys = keys

    async def on_submit(self, interaction: discord.Interaction):
        for key in self.keys:
            item = self.__getattribute__(key)
            value = item['input'].value
            self.backpack_menu.set_stat_filter(key, value)
        self.backpack_menu.reset_contextual_state()
        await self.backpack_menu.do_change_source(interaction)

    @staticmethod
    def build_input(label, value):
        v = value[0] if value and len(value) > 0 else None
        return discord.ui.TextInput(
            label=label,
            placeholder="e.g. >10, <100",
            default=v,
            style=discord.TextStyle.short,
            max_length=20,
            min_length=0,
            required=False
        )


class InteractiveBackpackSearchModal(discord.ui.Modal):
    def __init__(self, backpack_menu: InteractiveBackpackMenu, ctx: commands.Context):
        super().__init__(title='Backpack Search')
        self.ctx = ctx
        self.backpack_menu = backpack_menu
        self.search_name_input = self.build_input(
            label="Search by item name (case insensitive)",
            value=backpack_menu.search_name_text,
            placeholder="e.g. strange")
        self.search_slots_input = self.build_input(
            label="Search by slots names (case insensitive)",
            value=backpack_menu.search_slots_text,
            placeholder="e.g. belt,neck,2-hand")
        self.search_set_input = self.build_input(
            label="Search by exact set name (case sensitive)",
            value=backpack_menu.search_set_text,
            placeholder="e.g. The King of Mages")
        self.add_item(self.search_name_input)
        self.add_item(self.search_slots_input)
        self.add_item(self.search_set_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.backpack_menu._search_name_text = self.search_name_input.value
        self.backpack_menu._search_slots_text = self.search_slots_input.value
        self.backpack_menu._search_set_text = self.search_set_input.value
        self.backpack_menu.reset_contextual_state()
        await self.backpack_menu.do_change_source(interaction)

    @staticmethod
    def build_input(label, value, placeholder=""):
        return discord.ui.TextInput(
            label=label,
            default=value,
            placeholder=placeholder,
            style=discord.TextStyle.short,
            max_length=100,
            min_length=0,
            required=False
        )


class InteractiveBackpackLootModal(discord.ui.Modal):
    def __init__(self, backpack_menu: InteractiveBackpackMenu, ctx: commands.Context, rarity, max_value, title=None):
        actual_title = "How many {} chests to open?".format(rarity) if title is None else title
        super().__init__(title=actual_title)
        self.ctx = ctx
        self.backpack_menu = backpack_menu
        self.rarity = rarity
        self.max_value = max_value
        self.loot_input = self.build_input()
        self.add_item(self.loot_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.backpack_menu.do_open_loot(interaction, self.rarity, int(self.loot_input.value))

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        if int(self.loot_input.value) < 1 or int(self.loot_input.value) > min(100, self.max_value):
            raise Exception("User entered an incorrect loot box value")
        return True

    def build_input(self):
        return discord.ui.TextInput(
            label="Enter a value up to {}".format(min(100, self.max_value)),
            style=discord.TextStyle.short,
            max_length=100,
            min_length=0,
            required=True
        )


class InteractiveSetSelect(discord.ui.Select):
    def __init__(self, backpack_menu: InteractiveBackpackMenu, ctx: commands.Context, sets, row=0):
        placeholder = "[Select a set]"
        super().__init__(min_values=1, max_values=1, row=row, placeholder=placeholder)
        self.backpack_menu = backpack_menu
        self.ctx = ctx
        self.build_options(sets)

    async def callback(self, interaction: Interaction[ClientT]) -> Any:
        await self.backpack_menu.do_change_setinfo_source(interaction=interaction, set_name=self.values[0])

    def build_options(self, sets):
        set_bonuses = self.ctx.bot.get_cog("Adventure").SET_BONUSES
        for set_name in set_bonuses:
            total, own = sets[set_name]
            label = "{} ({}/{})".format(set_name, own, total)
            if own == total:
                label += " ✅"
            self.add_option(label=label, value=set_name)
