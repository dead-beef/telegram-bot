import os
from pony.orm import flush

from .db import sqlite3, db, get_page, get_or_create, update_or_create
from .tg import (
    User, Chat, Message, UserPhone, Alias,
    StickerSet, Sticker, SearchQuery, SearchLog
)
from .game import (
    PokemonType, PokemonTypeEffectiveness, PokemonExpType,
    PokemonExpToLevel, PokemonHabitat, Pokemon,
    PokemonEvolution, Move, PokemonMove, UserPokemon,
    UserPokemonMove, Item, UserItem, PokemonBattle,
    PokemonBattleMember
)


def connect(path):
    db.bind('sqlite', path, create_db=True)
    db.generate_mapping(create_tables=True)
    return db

def get_db_path(root):
    return os.path.join(root, 'bot.db')
