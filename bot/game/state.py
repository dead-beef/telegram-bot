import logging
from random import randint, shuffle, choice
from itertools import chain


class GameState:
    logger = logging.getLogger(__name__)

    def __init__(self, db):
        self.db = db
        self.max_user_pokemon = 6
        self.max_pokemon_moves = 4

    def get_user_items(self, user):
        self.db.cursor.execute(
            'SELECT'
            '  `item`.`id`, `item`.`name`, `item`.`icon`,'
            '  `user_inventory`.`item_count`, `item`.`can_use_in_battle`,'
            '  `item`.`can_use_in_inventory`'
            ' FROM `user_inventory`'
            '  LEFT JOIN `item` ON `user_inventory`.`item_id` = `item`.`id`'
            ' WHERE `user_inventory`.`user_id` = ?',
            (user.id,)
        )
        return self.db.cursor.fetchall()

    def get_habitats(self):
        self.db.cursor.execute('SELECT `id`, `name` FROM `habitat`')
        return self.db.cursor.fetchall()

    def add_user_item(self, user, item_id, count):
        self.db.cursor.execute(
            'SELECT * FROM `item` WHERE `id`=?', (item_id,)
        )
        if not self.db.cursor.fetchone():
            raise ValueError('invalid item id: "%s"' % item_id)

        user_id = user.id

        self.db.cursor.execute(
            'SELECT `item_count` FROM `user_inventory`'
            ' WHERE `user_id`=? AND `item_id`=?',
            (user_id, item_id)
        )
        count_ = self.db.cursor.fetchone()
        count_ = count_[0] if count_ is not None else 0

        if count is None or count_ < 0:
            count = -1
        else:
            count = max(0, count + count_)

        if count == 0:
            self.db.cursor.execute(
                'DELETE FROM `user_inventory`'
                ' WHERE `user_id`=? AND `item_id`=?',
                (user_id, item_id)
            )
        else:
            self.db.cursor.execute(
                'INSERT OR REPLACE'
                ' INTO `user_inventory`(`user_id`, `item_id`, `item_count`)'
                ' VALUES (?, ?, ?)',
                (user_id, item_id, count)
            )

    def add_user_items_default(self, user):
        default_items = [(4, 10), (24, 1), (29, 1), (39, 1)]
        ret = []
        for item_id, max_count in default_items:
            self.db.cursor.execute(
                'SELECT `item_count`'
                ' FROM `user_inventory`'
                ' WHERE `user_id` = ? AND `item_id` = ?',
                (user.id, item_id)
            )
            row = self.db.cursor.fetchone()
            diff = 0
            if row is None:
                self.db.cursor.execute(
                    'INSERT INTO `user_inventory`'
                    ' (`user_id`, `item_id`, `item_count`)'
                    ' VALUES(?, ?, ?)',
                    (user.id, item_id, max_count)
                )
                diff = max_count
            elif row[0] >= 0 and row[0] < max_count:
                diff = max_count - row[0]
                self.db.cursor.execute(
                    'UPDATE `user_inventory`'
                    ' SET `item_count`=? WHERE `user_id`=? AND `item_id`=?',
                    (max_count, user.id, item_id)
                )
            self.db.cursor.execute(
                'SELECT `icon`, `name` FROM `item` WHERE `id`=?',
                (item_id,)
            )
            row = self.db.cursor.fetchone()
            ret.append((row[0], row[1], diff))
        self.db.save()
        return ret

    def remove_user_item(self, user_id, item_id, count=1):
        self.db.cursor.execute(
            'SELECT `item_count` FROM `user_inventory`'
            ' WHERE `user_id`=? AND `item_id`=?',
            (user_id, item_id)
        )
        count_ = self.db.cursor.fetchone()
        if count_ is None:
            return
        if count_ <= count:
            self.db.cursor.execute(
                'DELETE FROM `user_inventory`'
                ' WHERE `user_id`=? AND `item_id`=?',
                (user_id, item_id)
            )
        else:
            self.db.cursor.execute(
                'UPDATE `user_inventory` SET `item_count`=?'
                ' WHERE `user_id`=? AND `item_id`=?',
                (count_ - count, user_id, item_id)
            )
        self.db.save()

    def get_user_pokemon(self, user):
        self.db.cursor.execute(
            'SELECT `up`.`id`, `t`.`icon`, COALESCE(`t2`.`icon`, \'\'),'
            '       `p`.`name`, `up`.`level`, `up`.`hp`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon` `p` ON `up`.`pokemon_id` = `p`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `p`.`type_id` = `t`.`id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `p`.`type_2_id` = `t2`.`id`'
            ' WHERE `up`.`user_id` = ?'
            ' ORDER BY `p`.`name`, `up`.`level`',
            (user.id,)
        )
        return [
            tuple(chain(data, (self.get_pokemon_stats(data[0])[0],)))
            for data in self.db.cursor.fetchall()
        ]

    def get_pokemon_stats(self, id_):
        self.db.cursor.execute(
            'SELECT `pokemon_id`, `level`, `iv_hp`, `iv_atk`,'
            '  `iv_sp_atk`, `iv_def`, `iv_sp_def`, `iv_speed`'
            ' FROM `user_pokemon`'
            ' WHERE `id`=?',
            (id_,)
        )
        row = self.db.cursor.fetchone()
        if row is None:
            raise ValueError('invalid pokemon id: %s' % id_)
        pid = row[0]
        level = row[1]
        iv_hp = row[2]
        ivs = row[3:]

        self.db.cursor.execute(
            'SELECT `hp`, `atk`, `sp_atk`, `def`, `sp_def`, `speed`'
            ' FROM `pokemon` WHERE `id`=?',
            (pid,)
        )
        row = self.db.cursor.fetchone()
        hp = row[0]
        stats = row[1:]

        hp = round((2 * hp + iv_hp) * level / 100) + level + 10
        stats = (
            round(2 * stat + iv / 100) + 5
            for stat, iv in zip(stats, ivs)
        )

        return list(chain((hp,), stats))

    def get_starter_pokemon(self):
        self.db.cursor.execute(
            'SELECT `p`.`id`, `t`.`icon`,'
            '       COALESCE(`t2`.`icon`, \'\'), `p`.`name`'
            ' FROM `pokemon` `p`'
            '  LEFT JOIN `pokemon_type` `t` ON `p`.`type_id` = `t`.`id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `p`.`type_2_id` = `t2`.`id`'
            ' WHERE `p`.`is_starter` > 0'
        )
        return self.db.cursor.fetchall()

    def get_move_count(self, id_):
        self.db.cursor.execute(
            'SELECT COUNT(*) FROM `user_pokemon_move`'
            ' WHERE `user_pokemon_id`=?',
            (id_,)
        )
        return self.db.cursor.fetchone()[0]

    def get_available_moves(self, id_):
        self.db.cursor.execute(
            'SELECT `m`.`id`, `m`.`pp`, `t`.`icon`, `m`.`name`,'
            '       CASE WHEN `upm`.`pp` IS NULL THEN 0 ELSE 1 END'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon_move` `pm`'
            '   ON `up`.`pokemon_id` = `pm`.`pokemon_id`'
            '  LEFT JOIN `move` `m` ON `pm`.`move_id` = `m`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `m`.`type_id` = `t`.`id`'
            '  LEFT JOIN `user_pokemon_move` `upm`'
            '   ON `upm`.`user_pokemon_id`=`up`.`id`'
            '    AND `upm`.`move_id` = `m`.`id`'
            ' WHERE `up`.`id`=?'
            '  AND `pm`.`min_level` <= `up`.`level`',
            (id_,)
        )
        return self.db.cursor.fetchall()

    def get_evolutions(self, id_):
        self.db.cursor.execute(
            'SELECT DISTINCT `p`.`id`, `t`.`icon`,'
            '                COALESCE(`t2`.`icon`, \'\'), `p`.`name`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon_evolution` `pe`'
            '            ON `pe`.`from`=`up`.`pokemon_id`'
            '  LEFT JOIN `pokemon` `p` ON `p`.`id`=`pe`.`to`'
            '  LEFT JOIN `pokemon_type` `t` ON `p`.`type_id` = `t`.`id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `p`.`type_2_id` = `t2`.`id`'
            ' WHERE `up`.`id`=? AND `pe`.`to` IS NOT NULL',
            (id_,)
        )
        return self.db.cursor.fetchall()

    def is_move_available(self, id_, move_id):
        self.db.cursor.execute(
            'SELECT COUNT(*)'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon_move` `pm`'
            '   ON `up`.`pokemon_id` = `pm`.`pokemon_id`'
            '  LEFT JOIN `move` `m` ON `pm`.`move_id` = `m`.`id`'
            ' WHERE `up`.`id`=? AND `m`.`id`=?'
            '  AND `pm`.`min_level` <= `up`.`level`',
            (id_, move_id)
        )
        return bool(self.db.cursor.fetchone())

    def add_move(self, id_, move_id):
        if self.get_move_count(id_) >= self.max_pokemon_moves:
            raise ValueError('too many moves')
        if not self.is_move_available(id_, move_id):
            raise ValueError('move is not available')
        self.db.cursor.execute(
            'SELECT `pp` FROM `move` WHERE `id`=?',
            (move_id,)
        )
        pp = self.db.cursor.fetchone()[0]
        self.db.cursor.execute(
            'INSERT OR REPLACE INTO `user_pokemon_move`'
            ' (`user_pokemon_id`, `move_id`, `pp`, `max_pp`)'
            ' VALUES(?, ?, ?, ?)',
            (id_, move_id, 0, pp)
        )
        self.db.save()

    def delete_move(self, id_, move_id):
        if self.get_move_count(id_) <= 1:
            raise ValueError('too few moves')
        self.db.cursor.execute(
            'DELETE FROM `user_pokemon_move`'
            ' WHERE `user_pokemon_id`=? AND `move_id`=?',
            (id_, move_id)
        )
        self.db.save()

    def add_random_moves(self, id_, move_count=1):
        count = self.get_move_count(id_)
        if count + move_count > self.max_pokemon_moves:
            raise ValueError('too many moves')
        moves = [
            move for move in self.get_available_moves(id_)
            if not move[-1]
        ]
        shuffle(moves)
        moves = moves[:move_count]
        self.logger.info('moves: %s', moves)
        if not moves:
            raise ValueError('no more moves available')
        ret = []
        for move in moves:
            move_id = move[0]
            pp = move[1]
            self.db.cursor.execute(
                'INSERT INTO `user_pokemon_move`'
                ' (`user_pokemon_id`, `move_id`, `pp`, `max_pp`)'
                ' VALUES(?, ?, ?, ?)',
                (id_, move_id, pp, pp)
            )
            ret.append(move_id)
        self.db.save()
        return ret

    def add_pokemon_exp(self, id_, exp):
        self.db.cursor.execute(
            'SELECT `pokemon_id`, `exp`, `level`'
            'FROM `user_pokemon` WHERE `id`=?',
            (id_,)
        )
        pid, exp_, level_ = self.db.cursor.fetchone()
        exp += exp_
        self.db.cursor.execute(
            'SELECT `e`.`level` FROM `pokemon` `p`'
            ' LEFT JOIN `pokemon_exp_to_level` `e`'
            '  ON `p`.`exp_type_id`=`e`.`exp_type_id`'
            ' WHERE `p`.`id`=? AND `e`.`exp`>=?'
            ' ORDER BY `e`.`exp` ASC LIMIT 1',
            (pid, exp)
        )
        level = self.db.cursor.fetchone()[0]
        self.db.cursor.execute(
            'UPDATE `user_pokemon`'
            ' SET `exp`=?, `level`=?'
            ' WHERE `id`=?',
            (exp, level, id_)
        )
        level_changed = level != level_
        self.db.save()
        return level_changed

    def evolve_pokemon(self, id_, new_pid):
        required = []
        self.db.cursor.execute(
            'SELECT `pe`.`min_level`, `pe`.`item_id`,'
            '       `up`.`user_id`, `up`.`level`,'
            '       `ui`.`item_count`, `i`.`name`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon_evolution` `pe`'
            '   ON `pe`.`from`=`up`.`pokemon_id`'
            '  LEFT JOIN `user_inventory` `ui`'
            '   ON `ui`.`user_id`=`up`.`user_id`'
            '      AND `ui`.`item_id`=`pe`.`item_id`'
            '  LEFT JOIN `item` `i` ON `i`.`id`=`pe`.`item_id`'
            ' WHERE `up`.`id`=? AND `pe`.`to`=?',
            (id_, new_pid)
        )
        ev = self.db.cursor.fetchall()
        if not ev:
            raise ValueError('invalid evolution')
        for min_level, item_id, user_id, level, item_count, item_name in ev:
            r = []
            if min_level is not None and level < min_level:
                r.append('level %d' % min_level)
            if item_id is not None and (item_count is None or item_count <= 0):
                if item_name:
                    r.append('item "%s"' % item_name)
                else:
                    r.append('item #%d' % item_id)
            if r:
                required.append('and'.join(r))
            else:
                if item_id is not None:
                    self.remove_user_item(user_id, item_id)
                self.db.cursor.execute(
                    'UPDATE `user_pokemon` SET `pokemon_id`=? WHERE `id`=?',
                    (new_pid, id_)
                )
                self.heal_pokemon(id_)
                return
        raise ValueError('required %s' % 'or'.join(required))

    def heal_pokemon(self, id_):
        stats = self.get_pokemon_stats(id_)
        self.db.cursor.execute(
            'UPDATE `user_pokemon` SET `hp`=? WHERE `id`=?',
            (stats[0], id_)
        )
        self.db.save()

    def heal(self, user):
        self.db.cursor.execute(
            'SELECT `id` FROM `user_pokemon` WHERE `user_id`=?',
            (user.id,)
        )
        ids = [row[0] for row in self.db.cursor.fetchall()]
        row_count = 0
        params = ','.join('?' for _ in ids)

        for id_ in ids:
            self.heal_pokemon(id_)
            row_count += self.db.cursor.rowcount

        self.db.cursor.execute(
            'UPDATE `user_pokemon_move` SET `pp`=`max_pp`'
            ' WHERE `user_pokemon_id` IN (%s)' % params,
            ids
        )
        row_count += self.db.cursor.rowcount

        self.db.save()
        return '%d rows affected' % row_count

    @staticmethod
    def randomize(stat):
        return stat * randint(75, 125) // 100

    @staticmethod
    def random_iv():
        return randint(0, 31)

    def create_pokemon(self, id_, user_id,
                       min_level, max_level, evolve=False):
        if user_id is not None:
            self.db.cursor.execute(
                'SELECT COUNT(*) FROM `user_pokemon` WHERE `user_id`=?',
                (user_id,)
            )
            count = self.db.cursor.fetchone()[0]
            if count >= self.max_user_pokemon:
                raise ValueError('inventory is full')

        level = randint(min_level, max_level)

        if evolve:
            while True:
                self.db.cursor.execute(
                    'SELECT `to` FROM `pokemon_evolution`'
                    ' WHERE `from`=? AND `min_level`>0'
                    ' AND `min_level`<=?',
                    (id_, level)
                )
                rows = self.db.cursor.fetchall()
                if not rows:
                    break
                id_ = choice(rows)[0]

        self.db.cursor.execute(
            'SELECT `p`.`height`, `p`.`weight`, `e`.`exp`'
            ' FROM `pokemon` `p`'
            '  LEFT JOIN `pokemon_exp_to_level` `e`'
            '   ON `p`.`exp_type_id` = `e`.`exp_type_id`'
            ' WHERE `p`.`id`=? AND `e`.`level`=?',
            (id_, level)
        )

        (height, weight, exp) = self.db.cursor.fetchone()

        height = self.randomize(height)
        weight = self.randomize(weight)
        hp = self.random_iv()
        atk = self.random_iv()
        sp_atk = self.random_iv()
        def_ = self.random_iv()
        sp_def = self.random_iv()
        speed = self.random_iv()

        self.db.cursor.execute(
            'INSERT INTO `user_pokemon`'
            ' (`user_id`, `pokemon_id`,`height`,`weight`,'
            '  `level`, `exp`, `iv_hp`, `iv_atk`, `iv_sp_atk`,'
            '  `iv_def`, `iv_sp_def`, `iv_speed`)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (user_id, id_, height, weight, -1, 0, hp,
             atk, sp_atk, def_, sp_def, speed)
        )
        ret = self.db.cursor.lastrowid
        self.add_pokemon_exp(ret, exp)
        self.add_random_moves(ret, self.max_pokemon_moves)
        self.heal_pokemon(ret)
        return ret

    def create_random_encounter(self, user_id,
                                habitat_id, min_level, max_level):
        self.db.cursor.execute(
            'SELECT `id` FROM `pokemon`'
            ' WHERE `habitat_id`=? ORDER BY RANDOM() LIMIT 1',
            (habitat_id,)
        )
        pid = self.db.cursor.fetchone()
        if pid is None:
            return 'no pokemon in habitat'
            #return None
        pid = pid[0]
        id_ = self.create_pokemon(pid, None, min_level, max_level, True)

        ret = self.pokemon_info(id_)
        self.remove_unused_pokemon()
        return ret

    def pokemon_info_short(self, id_):
        self.db.cursor.execute(
            'SELECT `t`.`icon`, COALESCE(`t2`.`icon`, \'\'), `p`.`name`,'
            '  `up`.`level`, `up`.`hp`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon` `p` ON `up`.`pokemon_id`=`p`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `t`.`id`=`p`.`type_id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `t2`.`id`=`p`.`type_2_id`'
            ' WHERE `up`.`id`=?',
            (id_,)
        )
        data = self.db.cursor.fetchone()
        if data is None:
            return 'pokemon "%s" does not exist' % id_
        stats = self.get_pokemon_stats(id_)
        return '%s%s %s LV %s HP %s / %s' % chain(data, (stats[0],))

    def pokemon_info(self, id_):
        self.db.cursor.execute(
            'SELECT `t`.`icon`, COALESCE(`t2`.`icon`, \'\'), `p`.`name`,'
            '  `up`.`level`, `up`.`exp`, `up`.`hp`,'
            '  `up`.`iv_hp`, `up`.`iv_atk`, `up`.`iv_sp_atk`,'
            '  `up`.`iv_def`, `up`.`iv_sp_def`, `up`.`iv_speed`,'
            '  CAST(`up`.`height` AS FLOAT) / 10.0,'
            '  CAST(`up`.`weight` AS FLOAT) / 10.0'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon` `p` ON `up`.`pokemon_id`=`p`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `t`.`id`=`p`.`type_id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `t2`.`id`=`p`.`type_2_id`'
            ' WHERE `up`.`id`=?',
            (id_,)
        )
        data = self.db.cursor.fetchone()
        if data is None:
            return 'pokemon "%s" does not exist' % id_
        stats = self.get_pokemon_stats(id_)
        ret = (
            '{0}{1} {2}\n'
            '`\n'
            'Height: {12:.1f}m\n'
            'Weight: {13:.1f}kg\n'
            '\n'
            'HP:     {5} / {14} | {6}\n'
            'LV:     {3}\n'
            'EXP:    {4}\n'
            '\n'
            'ATK:    {15:3} | {7:2}\n'
            'SP.ATK: {16:3} | {8:2}\n'
            'DEF:    {17:3} | {9:2}\n'
            'SP.DEF: {18:3} | {10:2}\n'
            'SPD:    {19:3} | {11:2}\n'
            '`\n'
            'Moves:\n'
        ).format(*chain(data, stats))
        self.db.cursor.execute(
            'SELECT `t`.`icon`, `m`.`name`, `um`.`pp`, `m`.`pp`'
            ' FROM `user_pokemon_move` `um`'
            '  LEFT JOIN `move` `m` ON `um`.`move_id`=`m`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `t`.`id`=`m`.`type_id`'
            ' WHERE `um`.`user_pokemon_id`=?',
            (id_,)
        )
        moves = self.db.cursor.fetchall()
        if moves:
            ret += '\n'.join(
                '%s %s  %d / %d' % move
                for move in moves
            )
        else:
            ret += 'none'
        return ret

    def is_in_battle(self, user_id):
        self.db.cursor.execute(
            'SELECT COUNT(*) FROM `pokemon_battle_user` WHERE `user_id`=?',
            (user_id,)
        )
        return bool(self.db.cursor.fetchone()[0])

    def flee(self, user_id):
        self.db.cursor.execute(
            'DELETE FROM `pokemon_battle`'
            ' WHERE `id` IN ('
            '  SELECT DISTINCT `pokemon_battle_id`'
            '   FROM `pokemon_battle_user` WHERE `user_id`=?'
            ' )',
            (user_id,)
        )
        ret = self.db.cursor.rowcount
        self.remove_unused_pokemon()
        return ret

    def remove_unused_pokemon(self):
        self.db.cursor.execute(
            'DELETE FROM `user_pokemon` WHERE `id` IN ('
            '  SELECT `up`.`id` FROM `user_pokemon` `up`'
            '    LEFT JOIN `pokemon_battle_user` `b`'
            '     ON `b`.`user_pokemon_id`=`up`.`id`'
            '    WHERE `up`.`user_id` IS NULL'
            '     AND `b`.`user_pokemon_id` IS NULL'
            ')'
        )
        self.db.save()
        return self.db.cursor.rowcount

    def release_pokemon(self, id_):
        self.db.cursor.execute(
            'SELECT `t`.`icon`, COALESCE(`t2`.`icon`, \'\'), `p`.`name`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon` `p` ON `up`.`pokemon_id`=`p`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `p`.`type_id`=`t`.`id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `p`.`type_2_id`=`t2`.`id`'
            ' WHERE `up`.`id`=?',
            (id_,)
        )
        mon = self.db.cursor.fetchone()
        if mon is None:
            return 'pokemon "%d" does not exist' % id_
        self.db.cursor.execute(
            'DELETE FROM `user_pokemon` WHERE `id`=?',
            (id_,)
        )
        self.db.save()
        return 'released %s%s %s' % mon
