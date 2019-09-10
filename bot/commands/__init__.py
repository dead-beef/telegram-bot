from .base import BotCommandBase
from .data import DataCommandMixin
from .game import GameCommandMixin
from .misc import MiscCommandMixin
from .search import SearchCommandMixin
from .settings import SettingsCommandMixin


class BotCommands(SettingsCommandMixin, DataCommandMixin,
                  GameCommandMixin, SearchCommandMixin, MiscCommandMixin,
                  BotCommandBase):
    pass
