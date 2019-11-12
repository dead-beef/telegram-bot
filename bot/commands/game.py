from pony.orm import select
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode
)

from bot.util import (
    chunks,
    command,
    get_command_args,
    check_callback_user,
    Permission as P,
    CommandType as C
)
from bot.models import (
    User, UserItem, Pokemon, UserPokemon, PokemonHabitat
)


class GameCommandMixin:
    def __init__(self, bot):
        super().__init__(bot)
        self.help = self.help + (
            '\n'
            '/starter - get starter pokemon\n'
            '/getitems - get items\n'
            '/inv - view inventory\n'
            '/mon - view pokemon\n'
            '/heal - heal pokemon\n'
            '/encounter - start a random encounter\n'
            '/flee - flee from all battles\n'
            '/give <item> <count> - give item\n'
        )

    @command(C.NONE)
    def cmd_inv(self, _, update):
        user = User.from_tg(update.message.from_user)
        if user.in_battle is not None:
            update.message.reply_text('user is in a battle', quote=True)
            return
        items = user.items.select()[:]
        if not items:
            update.message.reply_text('no items', quote=True)
            return
        res = ''
        keyboard = []
        for item in items:
            res += '%s %s    x%s\n' % (
                item.item.icon, item.item.name,
                item.count if item.count >= 0 else '\u221e'
            )
            #if can_use:
            #    keyboard.append([
            #        InlineKeyboardButton(
            #            '%s %s' % (icon, name),
            #            callback_data='iuse %s' % id_
            #        )
            #    ])
        if not keyboard:
            keyboard = None
        else:
            keyboard = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(res, quote=True, reply_markup=keyboard)

    @command(C.REPLY_TEXT, P.ADMIN)
    def cmd_give(self, _, update):
        usage = 'usage: /give <item> <count>'
        args = get_command_args(update.message, help=usage)
        args = args.split()
        if len(args) > 2:
            return usage, True
        item = int(args[0])
        count = int(args[1]) if len(args) > 1 else None
        if not update.message.reply_to_message:
            return 'not a reply', True
        user = User.from_tg(update.message.reply_to_message.from_user)
        user.add_item(item, count)
        return 'done'

    def cb_iuse(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        user = User.from_tg(user)
        if user.in_battle is not None:
            return
        item = update.callback_query.data
        update.callback_query.message.edit_text(
            'use item "%s"' % item
        )

    @command(C.REPLY_TEXT)
    def cmd_getitems(self, _, update):
        user = User.from_tg(update.message.from_user)
        if user.in_battle is not None:
            update.message.reply_text('user is in a battle', quote=True)
            return

        default_items = [(4, 10), (24, 1), (29, 1), (39, 1)]
        res = []

        for item_id, max_count in default_items:
            item = user.items.select(lambda i: i.item.id == item_id)[:1]
            if not item:
                diff = max_count
                item = UserItem(item=item_id, user=user, count=max_count)
            else:
                item = item[0]
                diff = max(0, max_count - item.count)
                item.count += diff
            res.append((item.item.icon, item.item.name, diff))

        res = '\n'.join('%s %s +%d' % item for item in res)
        return res, True

    @command(C.REPLY_TEXT)
    def cmd_heal(self, _, update):
        user = User.from_tg(update.message.from_user)
        if user.in_battle is not None:
            return 'user is in a battle', True
        user.heal()
        return 'done', True

    @command(C.NONE)
    def cmd_starter(self, _, update):
        user = User.from_tg(update.message.from_user)
        if user.pokemon:
            update.message.reply_text(
                'user already has a pokemon',
                quote=True
            )
            return
        starters = Pokemon.get_starters()
        keyboard = chunks([
            InlineKeyboardButton(
                str(starter.id),
                callback_data='starter %s' % starter.id
            )
            for starter in starters
        ], 5)
        res = '\n'.join(
            '%s. %s' % (starter.id, starter.full_name)
            for starter in starters
        )
        keyboard = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(res, quote=True, reply_markup=keyboard)

    def cb_starter(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        user = User.from_tg(user)
        if user.pokemon:
            update.callback_query.message.edit_text(
                'user already has a pokemon'
            )
            return
        pokemon = Pokemon[int(update.callback_query.data)]
        pokemon = UserPokemon.create(pokemon, user, 5, 5)
        update.callback_query.message.edit_text(
            pokemon.info_full,
            parse_mode=ParseMode.MARKDOWN
        )

    def _mon(self, user):
        res = '\n'.join(p.info_short for p in user.pokemon)
        if not res:
            return 'no pokemon', None
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                p.pokemon.full_name,
                callback_data='mon %s' % p.id
            )]
            for p in user.pokemon
        ])
        return res, keyboard

    @command(C.NONE)
    def cmd_mon(self, _, update):
        user = User.from_tg(update.message.from_user)
        res, keyboard = self._mon(user)
        update.message.reply_text(res, quote=True, reply_markup=keyboard)

    def cb_mon(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        user = User.from_tg(user)

        args = update.callback_query.data.split()
        pid = int(args[0]) if args else None
        action = args[1] if len(args) > 1 else None
        pid2 = int(args[2]) if len(args) > 2 else None

        if action is not None and user.in_battle is not None:
            return

        if pid is not None:
            pokemon = user.pokemon.select(lambda p: p.id == pid)[:1]
            if pokemon:
                pokemon = pokemon[0]
        else:
            pokemon = None

        if not pokemon:
            res, keyboard = self._mon(user)
        else:
            res = None
            keyboard = None
            r = InlineKeyboardButton('release',
                                     callback_data='mon %d r' % pid)
            rr = InlineKeyboardButton('confirm release',
                                      callback_data='mon %d rr' % pid)
            ev = InlineKeyboardButton('evolve',
                                      callback_data='mon %d e' % pid)
            m = InlineKeyboardButton('moves',
                                     callback_data='mmove %d' % pid)
            back = InlineKeyboardButton('back', callback_data='mon')

            if action == 'rr':
                res = 'released %s' % pokemon.info_short
                pokemon.delete()
                keyboard = [back]
            elif action == 'r':
                keyboard = [rr, ev, m, back]
            elif action == 'e':
                if pid2 is not None:
                    try:
                        pokemon.evolve(pid2)
                        keyboard = [r, ev, m, back]
                    except ValueError as ex:
                        res = str(ex)
                if pid2 is None or keyboard is None:
                    keyboard = [
                        InlineKeyboardButton(
                            to.full_name,
                            callback_data='mon %d e %d' % (pid, to.id)
                        )
                        for to in select(
                            ev.to for ev in pokemon.pokemon.evolutions
                        )
                    ]
                    keyboard.append(InlineKeyboardButton(
                        'back',
                        callback_data='mon %d' % pid
                    ))

            if res is None:
                res = pokemon.info_full
            if keyboard is None:
                keyboard = [r, ev, m, back]
            keyboard = InlineKeyboardMarkup(chunks(keyboard, 2))

        update.callback_query.message.edit_text(
            res,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    def cb_mmove(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        user = User.from_tg(user)

        args = update.callback_query.data.split()
        pid = int(args[0]) if args else None
        action = args[1] if len(args) > 1 else None

        res = ''

        if not pid:
            return

        pokemon = user.pokemon.select(lambda p: p.id == pid)[:1]
        if pokemon:
            pokemon = pokemon[0]
        else:
            return

        if action is not None:
            if user.in_battle is not None:
                return
            move_id = int(action[1:])
            try:
                if action[0] == '-':
                    pokemon.delete_move(move_id)
                else:
                    pokemon.add_move(move_id)
            except ValueError as ex:
                res = '\n\n%s' % str(ex)

        moves = pokemon.get_available_moves()
        used = set(m.move.id for m in pokemon.moves)

        res = pokemon.info_full + res
        back = [InlineKeyboardButton('back', callback_data='mon %d' % pid)]
        
        keyboard = [
            InlineKeyboardButton(
                '%s%s %s' % (
                    '-' if move.move.id in used else '+',
                    move.move.name, move.move.pp
                ),
                callback_data='mmove %d %s%d' % (
                    pid,
                    '-' if move.move.id in used else '+',
                    move.move.id
                )
            )
            for move in moves
        ]
        keyboard = list(chunks(keyboard, 2))
        keyboard.append(back)
        keyboard = InlineKeyboardMarkup(keyboard)

        update.callback_query.message.edit_text(
            res,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    @command(C.REPLY_TEXT)
    def cmd_flee(self, _, update):
        user = update.message.from_user
        user = User.from_tg(user)
        user.flee()
        return 'done', True

    @command(C.NONE)
    def cmd_encounter(self, _, update):
        user = User.from_tg(update.message.from_user)

        if user.in_battle is not None:
            update.message.reply_text('user is in a battle', quote=True)
            return

        keyboard = [
            InlineKeyboardButton(
                habitat.name,
                callback_data='elevel %d' % habitat.id
            )
            for habitat in PokemonHabitat.select()
        ]
        keyboard = list(chunks(keyboard, 3))
        keyboard = InlineKeyboardMarkup(keyboard)

        update.message.reply_text(
            'habitat:',
            reply_markup=keyboard,
            quote=True
        )

    @command(C.NONE)
    def cb_elevel(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        user = User.from_tg(user)
        if user.in_battle is not None:
            return

        hid = int(update.callback_query.data)

        keyboard = [
            InlineKeyboardButton(
                '%d-%d' % ((level - 1) * 10 + 1, level * 10),
                callback_data='estart %d %d' % (hid, level * 10)
            )
            for level in range(1, 11)
        ]
        keyboard = list(chunks(keyboard, 4))
        keyboard = InlineKeyboardMarkup(keyboard)

        update.callback_query.message.edit_text(
            'level:',
            reply_markup=keyboard
        )

    @command(C.NONE)
    def cb_estart(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        user = User.from_tg(user)
        if user.in_battle is not None:
            return

        args = update.callback_query.data.split()
        hid = int(args[0])
        max_level = int(args[1])
        min_level = max_level - 9

        res = UserPokemon.create_encounter(hid, min_level, max_level)
        res = res.info_full
        UserPokemon.remove_unused()

        update.callback_query.message.edit_text(
            res,
            parse_mode=ParseMode.MARKDOWN
        )
