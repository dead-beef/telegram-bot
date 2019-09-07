from .base import BotCommandBase
from .data import DataCommandMixin
from .misc import MiscCommandMixin
from .search import SearchCommandMixin
from .settings import SettingsCommandMixin


class BotCommands(SettingsCommandMixin, DataCommandMixin,
                  SearchCommandMixin, MiscCommandMixin,
                  BotCommandBase):
    pass
