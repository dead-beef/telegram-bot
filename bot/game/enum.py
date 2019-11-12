from enum import IntEnum


class DamageClass(IntEnum):
    STATUS = 1
    PHYSICAL = 2
    SPECIAL = 3


class Target(IntEnum):
    USER = 7
    RANDOM_OPPONENT = 8
    ALL_OTHER = 9
    SELECTED = 10
    ALL_OPPONENTS = 11


class Effect(IntEnum):
    REGULAR = 1


class InputType(IntEnum):
    SELECT_ACTION = 1
    SELECT_POKEMON = 2


class SelectedActionType(IntEnum):
    FIGHT = 0
    POKEMON = 1
    ITEM = 2
    RUN = 3


class ActionType(IntEnum):
    FIGHT = 0
    POKEMON = 1
    ITEM = 2
    RUN = 3
    CHARGE = 4
    RECHARGE = 5
    FIGHT_CHARGED = 6
    FIGHT_LOCKED = 7
