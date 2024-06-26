from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import List, Literal, MutableMapping, TypedDict

import discord

log = logging.getLogger("red.cogs.adventure")


@dataclass
class StatRange:
    stat_type: Literal["hp", "dipl"]
    min_stat: float
    max_stat: float
    win_percent: float

    def __getitem__(self, name: str):
        return getattr(self, name)

    def __str__(self):
        return "Main Stat: {stat_type}\nMin Stat: {min_stat:0.2f}\nMax Stat: {max_stat:0.2f}\nWin%: {win_percent:0.2f}".format(
            stat_type=self.stat_type, min_stat=self.min_stat, max_stat=self.max_stat, win_percent=self.win_percent * 100
        )

    def get(self, name: str, default=None):
        return getattr(self, name, default)

class Raid(TypedDict):
    main_action: str
    amount: float
    num_ppl: int
    success: bool
    auto_users: Dict[discord.Member, int]


class AdventureResults:
    """Object to store recent adventure results."""

    def __init__(self, num_raids: int):
        self._num_raids: int = num_raids
        self._last_raids: MutableMapping[int, List[Raid]] = {}

    def add_result(self, guild: discord.Guild, main_action: str, amount: float, num_ppl: int, success: bool,
                   manual_users: List[discord.Member], auto_users: List[discord.Member], exclusion_users: List):
        """Add result to this object.
        :main_action: Main damage action taken by the adventurers
            (highest amount dealt). Should be either "attack" or
            "talk". Running will just be notated by a 0 amount.
        :amount: Amount dealt.
        :num_ppl: Number of people in adventure.
        :success: Whether adventure was successful or not.
        :manual_users: List of users who have taken a manual action this turn - will be added to auto if not excluded.
        :auto_users: List of users who should is currently taking auto actions.
        :exclusion_users: List of users who should be excluded from auto list.
        """
        if guild.id not in self._last_raids:
            self._last_raids[guild.id] = []

        if len(self._last_raids.get(guild.id, [])) >= self._num_raids:
            try:
                self._last_raids[guild.id].pop(0)
            except IndexError:
                pass

        # add manual users to the next auto list
        saved_auto_users = {}
        for user in manual_users:
            saved_auto_users[user] = self._num_raids
        # auto users can only be added back in if they have been in here for less than num_raids
        raids = self._last_raids.get(guild.id, [])
        if len(raids) > 0:
            raid = raids[-1]
            for user in auto_users:
                if user not in raid["auto_users"]:
                    # if the user wasn't on the previous auto list, reset them
                    count = self._num_raids * 2
                    saved_auto_users[user] = count
                else:
                    count = raid["auto_users"][user]
                if count == 0:
                    # no more auto for this user
                    continue
                else:
                    saved_auto_users[user] = count - 1
        else:
            for user in auto_users:
                count = self._num_raids * 2
                saved_auto_users[user] = count - 1

        for user in exclusion_users:
            saved_auto_users.pop(user, None)

        self._last_raids[guild.id].append(
            Raid(main_action=main_action, amount=amount, num_ppl=num_ppl, success=success, auto_users=saved_auto_users)
        )

    def get_last_auto_users(self, guild: discord.Guild):
        raids = self._last_raids.get(guild.id, [])
        if len(raids) > 0:
            return list(raids[-1]["auto_users"].keys())
        else:
            return []

    def get_stat_range(self, guild: discord.Guild) -> StatRange:
        """Return reasonable stat range for monster pool to have based
        on last few raids' damage.

        :returns: Dict with stat_type, min_stat and max_stat.
        """
        # how much % to increase damage for solo raiders so that they
        # can't just solo every monster based on their own average
        # damage
        if guild.id not in self._last_raids:
            self._last_raids[guild.id] = []
        SOLO_RAID_SCALE: float = 0.25
        min_stat: float = 0.0
        max_stat: float = 0.0
        stat_type: str = "hp"
        win_percent: float = 0.0
        if len(self._last_raids.get(guild.id, [])) == 0:
            return StatRange(stat_type=stat_type, min_stat=min_stat, max_stat=max_stat, win_percent=win_percent)

        # tally up stats for raids
        num_attack = 0
        dmg_amount = 0
        num_talk = 0
        talk_amount = 0
        num_wins = 0
        stat_type = "hp"
        avg_amount = 0
        raids = self._last_raids.get(guild.id, [])
        raid_count = len(raids)
        if raid_count == 0:
            num_wins = self._num_raids // 2
            raid_count = self._num_raids
            win_percent = 0.5
        else:
            for raid in raids:
                if raid["main_action"] == "attack":
                    num_attack += 1
                    dmg_amount += raid["amount"]
                    if raid["num_ppl"] == 1:
                        dmg_amount += raid["amount"] * SOLO_RAID_SCALE
                else:
                    num_talk += 1
                    talk_amount += raid["amount"]
                    if raid["num_ppl"] == 1:
                        talk_amount += raid["amount"] * SOLO_RAID_SCALE
                log.debug(f"raid dmg: {raid['amount']}")
                if raid["success"]:
                    num_wins += 1
            if num_attack > 0:
                avg_amount = dmg_amount / num_attack
            if dmg_amount < talk_amount:
                stat_type = "dipl"
                avg_amount = talk_amount / num_talk
            win_percent = num_wins / raid_count
            min_stat = avg_amount * 0.75
            max_stat = avg_amount * 2
            # want win % to be at least 50%, even when solo
            # if win % is below 50%, scale back min/max for easier mons
            if win_percent < 0.5:
                min_stat = avg_amount * win_percent
                max_stat = avg_amount * 1.5
        return StatRange(stat_type=stat_type, min_stat=min_stat, max_stat=max_stat, win_percent=win_percent)

    def __str__(self):
        return str(self._last_raids)
