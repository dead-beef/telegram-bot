from enum import IntEnum


class ErrorType(IntEnum):
    NONE = 0
    BOT = 1
    OTHER = 2
    ALL = BOT | OTHER


class BotError(Exception):
    pass


class CommandError(BotError):
    pass
