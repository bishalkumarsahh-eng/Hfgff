# ==========================================================
# Copyright (c) 2026 ArtistBots
# All Rights Reserved.
#
# Project      : ArtistBots API Telegram Music Bot
# Powered By   : Artist
# Type         : API Based Telegram Music Bot
#
# Bot          : @ArtistApibot
# Channel      : https://t.me/artistbots
# GitHub       : https://github.com/elevenyts
#
# Unauthorized copying, modification, or redistribution
# of this source code without permission is prohibited.
# ==========================================================

import itertools

# Rotating emoji sequence shown on /play and on autoplay messages.
# Each call to next_play_emoji() advances to the next emoji in the list,
# wrapping back to the start once the end is reached — so consecutive
# /play (and autoplay) triggers each show a different emoji in turn.
PLAY_EMOJIS = ["💞", "✨", "🎶", "🌟", "🔥", "🎧", "🌈", "💫"]

_emoji_cycle = itertools.cycle(PLAY_EMOJIS)


def next_play_emoji() -> str:
    return next(_emoji_cycle)
