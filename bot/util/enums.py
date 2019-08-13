import enum


class Permission(enum.IntEnum):
    IGNORED = -2
    BANNED = -1
    USER = 0
    USER_2 = 1
    ADMIN = 255
    ROOT = 256


class CommandType(enum.IntEnum):
    NONE = 0
    REPLY_TEXT = 1
    REPLY_STICKER = 2
    GET_OPTIONS = 3
    SET_OPTION = 4
    REPLY_TEXT_PAGINATED = 5
