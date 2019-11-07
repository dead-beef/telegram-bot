from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode
)

from bot.game import GameState

from bot.util import (
    chunks,
    command,
    get_command_args,
    check_callback_user,
    Permission as P,
    CommandType as C
)


class GameCommandMixin:
    def __init__(self, bot):
        super().__init__(bot)
        self.game = GameState(self.state.db)
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
        user = update.message.from_user
        items = self.game.get_user_items(user)
        if not items:
            update.message.reply_text('no items', quote=True)
            return
        if self.game.is_in_battle(user.id):
            update.message.reply_text('user is in a battle', quote=True)
            return
        res = ''
        keyboard = []
        for id_, name, icon, count, _, can_use in items:
            res += '%s %s    x%s\n' % (
                icon, name,
                count if count >= 0 else '\u221e'
            )
            if can_use:
                keyboard.append([
                    InlineKeyboardButton(
                        '%s %s' % (icon, name),
                        callback_data='iuse %s' % id_
                    )
                ])
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
        user = update.message.reply_to_message.from_user
        self.game.add_user_item(user, item, count)
        return '%s rows affected' % self.game.db.cursor.rowcount, True

    def cb_iuse(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        if self.game.is_in_battle(user.id):
            return
        item = update.callback_query.data
        update.callback_query.message.edit_text(
            'use item "%s"' % item
        )

    @command(C.REPLY_TEXT)
    def cmd_getitems(self, _, update):
        user = update.message.from_user
        if self.game.is_in_battle(user.id):
            update.message.reply_text('user is in a battle', quote=True)
            return
        res = self.game.add_user_items_default(user)
        res = '\n'.join('%s %s +%d' % item for item in res)
        return res, True

    @command(C.REPLY_TEXT)
    def cmd_heal(self, _, update):
        user = update.message.from_user
        if self.game.is_in_battle(user.id):
            return 'user is in a battle', True
        res = self.game.heal(user)
        return res, True

    @command(C.NONE)
    def cmd_starter(self, _, update):
        user = update.message.from_user
        if self.game.get_user_pokemon(user):
            update.message.reply_text(
                'user already has a pokemon',
                quote=True
            )
            return
        res = self.game.get_starter_pokemon()
        keyboard = chunks([
            InlineKeyboardButton(
                str(p[0]),
                callback_data='starter %s' % p[0]
            )
            for p in res
        ], 5)
        res = '\n'.join('%s. %s%s %s' % row for row in res)
        keyboard = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(res, quote=True, reply_markup=keyboard)

    def cb_starter(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return
        if self.game.get_user_pokemon(user):
            update.callback_query.message.edit_text(
                'user already has a pokemon'
            )
            return
        pid = int(update.callback_query.data)
        pid = self.game.create_pokemon(pid, user.id, 1, 1)
        res = self.game.pokemon_info(pid)
        update.callback_query.message.edit_text(
            res,
            parse_mode=ParseMode.MARKDOWN
        )

    def _mon(self, user):
        mon = self.game.get_user_pokemon(user)
        res = '\n'.join(
            '{0}. {1}{2} {3} LV {4} HP {5} / {6}'.format(*m)
            for m in mon
        )
        if not res:
            return 'no pokemon', None
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                '{1}{2} {3}'.format(*m),
                callback_data='mon %s' % m[0]
            )]
            for m in mon
        ])
        return res, keyboard

    @command(C.NONE)
    def cmd_mon(self, _, update):
        user = update.message.from_user
        res, keyboard = self._mon(user)
        update.message.reply_text(res, quote=True, reply_markup=keyboard)

    def cb_mon(self, _, update):
        user = check_callback_user(update)
        if user is None:
            return

        args = update.callback_query.data.split()
        pid = int(args[0]) if args else None
        action = args[1] if len(args) > 1 else None
        pid2 = int(args[2]) if len(args) > 2 else None

        if action is not None and self.game.is_in_battle(user.id):
            return

        if not pid:
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
                res = self.game.release_pokemon(pid)
                keyboard = [back]
            elif action == 'r':
                keyboard = [rr, ev, m, back]
            elif action == 'e':
                if pid2 is not None:
                    try:
                        self.game.evolve_pokemon(pid, pid2)
                        keyboard = [r, ev, m, back]
                    except ValueError as ex:
                        res = str(ex)
                if pid2 is None or keyboard is None:
                    keyboard = [
                        InlineKeyboardButton(
                            '%s%s %s' % data[1:],
                            callback_data='mon %d e %d' % (pid, data[0])
                        )
                        for data in self.game.get_evolutions(pid)
                    ]
                    keyboard.append(back)

            if res is None:
                res = self.game.pokemon_info(pid)
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

        args = update.callback_query.data.split()
        pid = int(args[0]) if args else None
        action = args[1] if len(args) > 1 else None

        res = ''

        if not pid:
            return
        if action is not None:
            if self.game.is_in_battle(user.id):
                return
            move_id = int(action[1:])
            try:
                if action[0] == '-':
                    self.game.delete_move(pid, move_id)
                else:
                    self.game.add_move(pid, move_id)
            except ValueError as ex:
                res = '\n\n%s' % str(ex)

        moves = self.game.get_available_moves(pid)

        res = self.game.pokemon_info(pid) + res
        back = [InlineKeyboardButton('back', callback_data='mon %d' % pid)]
        keyboard = [
            InlineKeyboardButton(
                '%s%s %s' % ('-' if used else '+', name, pp),
                callback_data='mmove %d %s%d' % (
                    pid,
                    '-' if used else '+',
                    move_id
                )
            )
            for move_id, pp, icon, name, used in moves
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
        res = self.game.flee(user.id)
        return 'fled from %s battles' % res, True

    @command(C.NONE)
    def cmd_encounter(self, _, update):
        user = update.message.from_user
        if self.game.is_in_battle(user.id):
            update.message.reply_text('user is in a battle', quote=True)
            return

        keyboard = [
            InlineKeyboardButton(
                name,
                callback_data='elevel %d' % id_
            )
            for id_, name in self.game.get_habitats()
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
        if user is None or self.game.is_in_battle(user.id):
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
        if user is None or self.game.is_in_battle(user.id):
            return

        args = update.callback_query.data.split()
        hid = int(args[0])
        max_level = int(args[1])
        min_level = max_level - 9

        res = self.game.create_random_encounter(
            user.id, hid, min_level, max_level
        )

        update.callback_query.message.edit_text(
            res,
            parse_mode=ParseMode.MARKDOWN
        )