import logging
from random import randint

from pony.orm import (
    select, delete,
    PrimaryKey, Required, Optional, Set
)

from .db import db
from .tg import User


logger = logging.getLogger(__name__)
MAX_USER_POKEMON = 6
MAX_POKEMON_MOVES = 4


def randomize_stat(stat):
    return stat * randint(75, 125) // 100

def random_iv():
    return randint(0, 31)


class PokemonType(db.Entity):
    id = PrimaryKey(int)
    name = Required(str)
    icon = Required(str)

    atk_effectiveness = Set('PokemonTypeEffectiveness')
    def_effectiveness = Set('PokemonTypeEffectiveness')
    pokemon = Set('Pokemon')
    pokemon_2 = Set('Pokemon')
    moves = Set('Move')


class PokemonTypeEffectiveness(db.Entity):
    damage_type = Required(PokemonType, reverse='atk_effectiveness')
    target_type = Required(PokemonType, reverse='def_effectiveness')
    damage_factor = Required(int)


class PokemonExpType(db.Entity):
    id = PrimaryKey(int)
    name = Required(str)
    exp_to_level = Set('PokemonExpToLevel')

    pokemon = Set('Pokemon')

class PokemonExpToLevel(db.Entity):
    exp_type = Required(PokemonExpType)
    level = Required(int)
    exp = Required(int)


class PokemonHabitat(db.Entity):
    id = PrimaryKey(int)
    name = Required(str)

    pokemon = Set('Pokemon')


class Pokemon(db.Entity):
    id = PrimaryKey(int)
    name = Required(str)
    image = Optional(str)
    type = Required(PokemonType, reverse='pokemon')
    type_2 = Optional(PokemonType, reverse='pokemon_2')
    exp_type = Required(PokemonExpType)
    habitat = Optional(PokemonHabitat)
    is_starter = Required(int)
    height = Required(int)
    weight = Required(int)
    base_hp = Required(int)
    base_atk = Required(int)
    base_sp_atk = Required(int)
    base_def = Required(int)
    base_sp_def = Required(int)
    base_speed = Required(int)
    capture_rate = Required(int)

    evolutions = Set('PokemonEvolution')
    pre_evolutions = Set('PokemonEvolution')
    moves = Set('PokemonMove')
    user_pokemon = Set('UserPokemon')

    @property
    def full_name(self):
        return '%s%s %s' % (
            self.type.icon,
            self.type_2.icon if self.type_2 is not None else '',
            self.name
        )

    @classmethod
    def get_starters(cls):
        return cls.select(lambda p: p.is_starter > 0)


class PokemonEvolution(db.Entity):
    from_ = Required(Pokemon, reverse='evolutions')
    to = Required(Pokemon, reverse='pre_evolutions')
    min_level = Required(int)
    item_id = Optional(int)


class Move(db.Entity):
    id = PrimaryKey(int)
    type = Optional(PokemonType)
    name = Required(str)
    pp = Required(int)
    damage_class_id = Required(int)
    priority = Required(int)
    power = Optional(int)
    accuracy = Optional(int)
    target_id = Required(int)
    effect_id = Required(int)
    effect_chance = Optional(int)
    ailment_id = Optional(int)
    ailment_chance = Optional(int)
    flinch_chance = Optional(int)
    category_id = Optional(int)
    min_hits = Optional(int)
    max_hits = Optional(int)
    min_turns = Optional(int)
    max_turns = Optional(int)
    drain = Optional(int)
    healing = Optional(int)
    crit_rate = Optional(int)

    can_learn = Set('PokemonMove')
    learned = Set('UserPokemonMove')


class PokemonMove(db.Entity):
    pokemon = Required(Pokemon)
    move = Required(Move)
    min_level = Required(int)


class UserPokemon(db.Entity):
    id = PrimaryKey(int, auto=True)
    user = Optional(User)
    pokemon = Required(Pokemon)
    height = Required(int)
    weight = Required(int)
    level = Required(int)
    exp = Required(int)
    hp = Required(int)
    iv_hp = Required(int)
    iv_atk = Required(int)
    iv_sp_atk = Required(int)
    iv_def = Required(int)
    iv_sp_def = Required(int)
    iv_speed = Required(int)

    moves = Set('UserPokemonMove')
    in_battle = Optional('PokemonBattleMember')

    @property
    def max_hp(self):
        hp = int((2 * self.pokemon.base_hp + self.iv_hp) * self.level / 100)
        hp += self.level + 10
        return hp
    @property
    def atk(self):
        return self.get_stat('atk')
    @property
    def sp_atk(self):
        return self.get_stat('sp_atk')
    @property
    def def_(self):
        return self.get_stat('def')
    @property
    def sp_def(self):
        return self.get_stat('atk')
    @property
    def speed(self):
        return self.get_stat('speed')
    @property
    def acc(self):
        if self.in_battle:
            return int(100 * self.in_battle.get_stat_multiplier('acc'))
        return 100
    @property
    def ev(self):
        if self.in_battle:
            return int(100 * self.in_battle.get_stat_multiplier('ev'))
        return 100

    @property
    def info_short(self):
        return '%s LV %s HP %s / %s' % (
            self.pokemon.full_name,
            self.level, self.hp, self.max_hp
        )

    @property
    def info_full(self):
        return (
            '{0}\n'
            '`\n'
            'Height: {1:.1f}m\n'
            'Weight: {2:.1f}kg\n'
            '\n'
            'HP:     {3} / {4} | {5}\n'
            'LV:     {6}\n'
            'EXP:    {7}\n'
            '\n'
            'ATK:    {8:3} | {9:2}\n'
            'SP.ATK: {10:3} | {11:2}\n'
            'DEF:    {12:3} | {13:2}\n'
            'SP.DEF: {14:3} | {15:2}\n'
            'SPD:    {16:3} | {17:2}\n'
            '`\n'
            'Moves:\n'
            '{18}'
        ).format(
            self.pokemon.full_name,
            self.height / 10, self.weight / 10,
            self.hp, self.max_hp, self.iv_hp,
            self.level,
            self.exp,
            self.atk, self.iv_atk,
            self.sp_atk, self.iv_sp_atk,
            self.def_, self.iv_def,
            self.sp_def, self.iv_sp_def,
            self.speed, self.iv_speed,
            '\n'.join(
                '%s %s  %d / %d' % (
                    pm.move.type.icon,
                    pm.move.name,
                    pm.pp,
                    pm.max_pp
                )
                for pm in self.moves
            )
        )

    def get_stat(self, name):
        iv = getattr(self, 'iv_' + name)
        base = getattr(self.pokemon, 'base_' + name)
        stat = int((2 * base + iv) * self.level / 100) + 5
        if self.in_battle:
            mod = self.in_battle.get_stat_multiplier(name)
            stat = int(stat * mod)
        return stat

    def get_available_moves(self, not_learned=False):
        ret = self.pokemon.moves.select(lambda m: m.min_level <= self.level)
        if not_learned:
            learned = set(move.move.id for move in self.moves)
            ret = ret.filter(lambda move: move.move.id not in learned)
        return ret

    def add_move(self, move):
        if isinstance(move, PokemonMove):
            if move.pokemon != self.pokemon:
                pm = None
            else:
                pm = move
                move = pm.move
        else:
            if not isinstance(move, Move):
                move = Move.get(id=move)
                if move is None:
                    raise ValueError('invalid move')
            pm = PokemonMove.get(move=move, pokemon=self.pokemon)
        if pm is None or pm.min_level > self.level:
            raise ValueError('move is not available')
        if len(self.moves.select(lambda m: m.move == move)):
            return
        if len(self.moves) >= MAX_POKEMON_MOVES:
            raise ValueError('too many moves')
        UserPokemonMove(
            user_pokemon=self, move=move,
            pp=move.pp, max_pp=move.pp
        )

    def delete_move(self, move):
        if not isinstance(move, Move):
            move = Move.get(id=move)
            if move is None:
                raise ValueError('invalid move')
        delete(m for m in self.moves if m.move == move)

    def add_random_moves(self, move_count=1):
        count = len(self.moves)
        if count + move_count > MAX_POKEMON_MOVES:
            raise ValueError('too many moves')
        moves = self.get_available_moves(True).random(move_count)
        logger.info('moves: %s', moves)
        if not moves:
            raise ValueError('no more moves available')
        for move in moves:
            self.add_move(move)

    def add_exp(self, exp):
        self.exp += exp
        level = select(
            etl.level
            for etl in self.pokemon.exp_type.exp_to_level
            if etl.exp <= self.exp
        ).max()
        if level is None:
            level = 1
        if self.level == level:
            return False
        self.level = level
        return True

    def evolve(self, evolve_to):
        if not isinstance(evolve_to, Pokemon):
            evolve_to = Pokemon.get(id=evolve_to)
            if evolve_to is None:
                raise ValueError('invalid pokemon')

        evolutions = self.pokemon.evolutions.select(
            lambda ev: ev.to == evolve_to
        )[:]
        if not evolutions:
            raise ValueError('invalid evolution')

        required = []
        for ev in evolutions:
            r = []
            if ev.min_level is not None and self.level < ev.min_level:
                r.append('level %d' % ev.min_level)
            if ev.item_id is not None:
                item = self.user.items.select(
                    lambda i: i.item.id == ev.item_id
                )
                if not item:
                    item = Item.get(id=ev.item_id)
                    if item is None:
                        r.append('item #%d' % ev.item_id)
                    else:
                        r.append('item "%s"' % item.name)
            if r:
                required.append('and'.join(r))
            else:
                if ev.item_id is not None:
                    self.user.remove_item(ev.item_id)
                self.pokemon = evolve_to
                self.heal()
                return
        raise ValueError('required %s' % ', or '.join(required))

    def heal(self, amount=None, revive=True):
        if not revive and self.hp <= 0:
            raise ValueError('can not heal fainted pokemon')
        if amount is None:
            self.hp = self.max_hp
        elif amount < 0:
            self.hp = min(
                self.max_hp,
                self.hp - int(amount * self.max_hp / 100)
            )
        else:
            self.hp = min(self.max_hp, self.hp + amount)

    @classmethod
    def create(cls, pokemon, user, min_level, max_level, evolve=False):
        if user is not None:
            if len(user.pokemon) >= MAX_USER_POKEMON:
                raise ValueError('user has too many pokemon')

        level = randint(min_level, max_level)

        if evolve:
            while True:
                evolution = pokemon.evolutions.select(lambda ev: (
                    (ev.item_id is None and ev.min_level <= level)
                    or (
                        ev.item_id is not None
                        and max(32, ev.min_level) <= level
                    )
                )).random(1)
                if not evolution:
                    break
                pokemon = evolution[0].to

        ret = cls(
            user=user, pokemon=pokemon,
            level=0, hp=0, exp=0,
            height=randomize_stat(pokemon.height),
            weight=randomize_stat(pokemon.weight),
            iv_hp=random_iv(),
            iv_atk=random_iv(),
            iv_sp_atk=random_iv(),
            iv_def=random_iv(),
            iv_sp_def=random_iv(),
            iv_speed=random_iv()
        )

        exp = pokemon.exp_type.exp_to_level.select(
            lambda e: e.level == level
        )[:]
        if not exp:
            exp = level
        else:
            exp = exp[0].exp

        ret.add_exp(exp)
        ret.heal()
        ret.add_random_moves(MAX_POKEMON_MOVES)

        return ret

    @classmethod
    def create_encounter(cls, habitat, min_level, max_level):
        if not isinstance(habitat, PokemonHabitat):
            habitat = PokemonHabitat.get(id=habitat)
            if habitat is None:
                raise ValueError('invalid habitat')
        pokemon = habitat.pokemon.random(1)
        if not pokemon:
            raise ValueError('no pokemon in habitat')
        ret = cls.create(pokemon[0], None, min_level, max_level, True)
        return ret

    @classmethod
    def remove_unused(cls):
        delete(p for p in cls if p.user is None and p.in_battle is None)


class UserPokemonMove(db.Entity):
    user_pokemon = Required(UserPokemon)
    move = Required(Move)
    pp = Required(int)
    max_pp = Required(int)

    in_battle = Optional('PokemonBattleMember')


class Item(db.Entity):
    id = PrimaryKey(int)
    name = Required(str)
    icon = Required(str)

    user_items = Set('UserItem')


class UserItem(db.Entity):
    user = Required(User)
    item = Required(Item)
    count = Required(int)


class PokemonBattle(db.Entity):
    id = PrimaryKey(int, auto=True)
    members = Set('PokemonBattleMember')


class PokemonBattleMember(db.Entity):
    id = PrimaryKey(int, auto=True)
    battle = Required(PokemonBattle)
    user = Optional(User)
    pokemon = Optional(UserPokemon)

    action = Optional(int)
    move = Optional(UserPokemonMove)
    duration = Optional(int)

    atk_stage = Required(int, default=0)
    sp_atk_stage = Required(int, default=0)
    def_stage = Required(int, default=0)
    sp_def_stage = Required(int, default=0)
    speed_stage = Required(int, default=0)
    acc_stage = Required(int, default=0)
    ev_stage = Required(int, default=0)

    def get_stat_multiplier(self, name):
        stage = getattr(self, name + '_stage')
        if stage >= 0:
            return 1 + stage / 2
        return 2 / (2 + stage)
