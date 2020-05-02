from pony.orm import PrimaryKey, Required, Optional, Set

from .db import db, get_or_create


class User(db.Entity):
    id = PrimaryKey(int, size=64)
    first_name = Optional(str, nullable=True)
    last_name = Optional(str, nullable=True)
    username = Optional(str, nullable=True)
    permission = Required(int, default=0)
    last_update = Required(int, default=0, size=64)

    messages = Set('Message')
    search_queries = Set('SearchLog')
    phones = Set('UserPhone')
    pokemon = Set('UserPokemon')
    items = Set('UserItem')
    in_battle = Optional('PokemonBattleMember')

    @property
    def full_name(self):
        return ' '.join(
            name for name in (self.first_name, self.last_name)
            if name is not None
        )

    @property
    def name(self):
        ret = self.full_name
        if not ret:
            if self.username is not None:
                ret = '@' + self.username
            else:
                ret = str(self.id)
        return ret

    @classmethod
    def from_tg(cls, user):
        return get_or_create(
            cls, user.id,
            first_name=user.first_name, last_name=user.last_name,
            username=user.username
        )

    def heal(self):
        for p in self.pokemon:
            p.heal()

    def add_item(self, item_id, amount=1, max_amount=None):
        if not isinstance(item_id, int):
            item_id = item_id.id
        item = self.items.select(lambda i: i.item.id == item_id)[:]
        if item:
            if max_amount is not None:
                item.count = min(max_amount, amount + item.count)
            else:
                item.count += amount
        else:
            self.items.create(item=item_id, count=amount)

    def remove_item(self, item_id, amount=1):
        if not isinstance(item_id, int):
            item_id = item_id.id
        item = self.items.select(lambda i: i.item.id == item_id)[:]
        if not item or item[0].count < amount:
            raise ValueError('not enough item #%d' % amount)
        item = item[0]
        if item.count == amount:
            item.delete()
        else:
            item.count -= amount

    def flee(self):
        if self.in_battle is not None:
            self.in_battle.battle.delete()


class Chat(db.Entity):
    id = PrimaryKey(int, size=64)
    title = Optional(str, nullable=True)
    invite_link = Optional(str, nullable=True)
    first_name = Optional(str, nullable=True)
    last_name = Optional(str, nullable=True)
    username = Optional(str, nullable=True)
    type = Required(str, default='private')
    last_update = Required(int, default=0, size=64)

    context = Optional(str, nullable=True)
    order = Optional(int, nullable=True)
    learn = Optional(int, nullable=True)
    reply_max_length = Optional(int, nullable=True)
    trigger = Optional(str, nullable=True)

    messages = Set('Message')
    aliases = Set('Alias')

    @classmethod
    def from_tg(cls, chat):
        return get_or_create(
            cls, chat.id,
            first_name=chat.first_name,
            last_name=chat.last_name,
            username=chat.username,
            title=chat.title,
            invite_link=chat.invite_link
        )


class Message(db.Entity):
    id_in_chat = Required(int, size=64)
    chat = Optional(Chat, nullable=True)
    user = Optional(User, nullable=True)
    timestamp = Required(int, size=64)
    text = Optional(str, nullable=True)
    file_id = Optional(str, nullable=True)
    file_path = Optional(str, nullable=True)
    file_name = Optional(str, nullable=True)
    sticker_id = Optional(str, nullable=True)
    inline_query = Optional(str, nullable=True)

    def __repr__(self):
        return 'Message(id_in_chat=%r)' % self.id_in_chat


class UserPhone(db.Entity):
    user = Required(User)
    phone = Required(str)
    timestamp = Required(int, size=64)


class Alias(db.Entity):
    id = PrimaryKey(int, auto=True)
    chat = Required(Chat)
    regexp = Required(str)
    replace = Required(str)


class StickerSet(db.Entity):
    id = PrimaryKey(int, auto=True)
    name = Required(str)
    title = Required(str)
    last_update = Required(int, size=64)
    stickers = Set('Sticker')


class Sticker(db.Entity):
    id = PrimaryKey(int, auto=True)
    set = Required(StickerSet)
    file_id = Required(str)
    emoji = Optional(str)


class SearchQuery(db.Entity):
    id = PrimaryKey(int, auto=True)
    query = Required(str)
    offset = Required(int, default=0)

    log = Set('SearchLog')


class SearchLog(db.Entity):
    id = PrimaryKey(int, auto=True)
    query = Required(SearchQuery)
    user = Required(User)
    timestamp = Required(int, size=64)
