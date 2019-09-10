import logging
from random import randint, shuffle


class GameState:
    logger = logging.getLogger(__name__)

    def __init__(self, db):
        self.db = db
        self.max_user_pokemon = 6
        self.max_pokemon_moves = 6

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
        default_items = [(4, 10), (24, 5), (29, 10), (39, 5)]
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

    def get_user_pokemon(self, user):
        self.db.cursor.execute(
            'SELECT `up`.`id`, `t`.`icon`, COALESCE(`t2`.`icon`, \'\'),'
            '       `p`.`name`, `up`.`level`, `up`.`hp`, `up`.`max_hp`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon` `p` ON `up`.`pokemon_id` = `p`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `p`.`type_id` = `t`.`id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `p`.`type_2_id` = `t2`.`id`'
            ' WHERE `up`.`user_id` = ?'
            ' ORDER BY `p`.`name`, `up`.`level`',
            (user.id,)
        )
        return self.db.cursor.fetchall()

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
            'INSERT OR REPLACE INTO `user_pokemon_move`'
            ' (`user_pokemon_id`, `move_id`, `pp`)'
            ' VALUES(?, ?, ?)',
            (id_, move_id, 0)
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
                ' (`user_pokemon_id`, `move_id`, `pp`)'
                ' VALUES(?, ?, ?)',
                (id_, move_id, pp)
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
        if level == level_:
            self.db.save()
            return False

        self.db.cursor.execute(
            'SELECT `base_hp`, `base_hp`, `base_atk`,'
            '  `base_sp_atk`, `base_def`, `base_sp_def`, `base_speed`'
            ' FROM `user_pokemon`'
            ' WHERE `id`=?',
            (id_,)
        )
        k = (1 + level / 50)
        stats = [int(stat * k) for stat in self.db.cursor.fetchone()]
        stats.append(id_)
        self.db.cursor.execute(
            'UPDATE `user_pokemon`'
            ' SET `hp`=?, `max_hp`=?, `atk`=?,'
            '  `sp_atk`=?, `def`=?, `sp_def`=?,'
            '  `speed`=?'
            ' WHERE `id`=?',
            stats
        )
        self.db.save()
        return True

    @staticmethod
    def randomize(stat):
        return stat * randint(75, 125) // 100

    def create_pokemon(self, id_, user_id, min_level, max_level):
        if user_id is not None:
            self.db.cursor.execute(
                'SELECT COUNT(*) FROM `user_pokemon` WHERE `user_id`=?',
                (user_id,)
            )
            count = self.db.cursor.fetchone()[0]
            if count >= self.max_user_pokemon:
                raise ValueError('inventory is full')

        level = randint(min_level, max_level)
        self.db.cursor.execute(
            'SELECT `p`.`height`, `p`.`weight`, `p`.`hp`, `p`.`atk`,'
            '  `p`.`sp_atk`, `p`.`def`, `p`.`sp_def`,'
            '  `p`.`speed`, `e`.`exp`'
            ' FROM `pokemon` `p`'
            '  LEFT JOIN `pokemon_exp_to_level` `e`'
            '   ON `p`.`exp_type_id` = `e`.`exp_type_id`'
            ' WHERE `p`.`id`=? AND `e`.`level`=?',
            (id_, level)
        )

        (height, weight, hp, atk, sp_atk,
         def_, sp_def, speed, exp) = self.db.cursor.fetchone()

        height = self.randomize(height)
        weight = self.randomize(weight)
        hp = self.randomize(hp)
        atk = self.randomize(atk)
        sp_atk = self.randomize(sp_atk)
        def_ = self.randomize(def_)
        sp_def = self.randomize(sp_def)
        speed = self.randomize(speed)

        self.db.cursor.execute(
            'INSERT INTO `user_pokemon`'
            ' (`user_id`, `pokemon_id`,`height`,`weight`,'
            '  `level`, `exp`, `base_hp`, `base_atk`, `base_sp_atk`,'
            '  `base_def`, `base_sp_def`, `base_speed`)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (user_id, id_, height, weight, -1, 0, hp,
             atk, sp_atk, def_, sp_def, speed)
        )
        ret = self.db.cursor.lastrowid
        self.add_pokemon_exp(ret, exp)
        self.add_random_moves(ret, 2)
        self.db.save()
        return ret

    def pokemon_info_short(self, id_):
        self.db.cursor.execute(
            'SELECT `t`.`icon`, COALESCE(`t2`.`icon`, \'\'), `p`.`name`,'
            '  `up`.`level`, `up`.`hp`, `up`.`max_hp`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon` `p` ON `up`.`pokemon_id`=`p`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `t`.`id`=`p`.`type_id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `t2`.`id`=`p`.`type_2_id`'
            ' WHERE `up`.`id`=?',
            (id_,)
        )
        stats = self.db.cursor.fetchone()
        if stats is None:
            return 'pokemon "%s" does not exist' % id_
        return '%s%s %s LV %s HP %s / %s' % stats

    def pokemon_info(self, id_):
        self.db.cursor.execute(
            'SELECT `t`.`icon`, COALESCE(`t2`.`icon`, \'\'), `p`.`name`,'
            '  `up`.`level`, `up`.`exp`, `up`.`hp`, `up`.`max_hp`,'
            '  `up`.`atk`, `up`.`sp_atk`, `up`.`def`, `up`.`sp_def`,'
            '  `up`.`speed`,'
            '  CAST(`up`.`height` AS FLOAT) / 10.0,'
            '  CAST(`up`.`weight` AS FLOAT) / 10.0'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon` `p` ON `up`.`pokemon_id`=`p`.`id`'
            '  LEFT JOIN `pokemon_type` `t` ON `t`.`id`=`p`.`type_id`'
            '  LEFT JOIN `pokemon_type` `t2` ON `t2`.`id`=`p`.`type_2_id`'
            ' WHERE `up`.`id`=?',
            (id_,)
        )
        stats = self.db.cursor.fetchone()
        if stats is None:
            return 'pokemon "%s" does not exist' % id_
        ret = (
            '{0}{1} {2}\n'
            '`\n'
            'Height: {12:.1f}m\n'
            'Weight: {13:.1f}kg\n'
            '\n'
            'HP:     {5} / {6}\n'
            'LV:     {3}\n'
            'EXP:    {4}\n'
            '\n'
            'ATK:    {7}\n'
            'SP.ATK: {8}\n'
            'DEF:    {9}\n'
            'SP.DEF: {10}\n'
            'SPD:    {11}\n'
            '`\n'
            'Moves:\n'
        ).format(*stats)
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
            'SELECT COUNT(*) FROM `pokemon_battle`'
            ' WHERE `user_id`=? OR `user_2_id`=?',
            (user_id, user_id)
        )
        return bool(self.db.cursor.fetchone()[0])

    def flee(self, user_id):
        self.db.cursor.execute(
            'DELETE FROM `pokemon_battle`'
            ' WHERE `user_id`=? OR `user_2_id`=?',
            (user_id, user_id)
        )
        ret = self.db.cursor.rowcount
        self.remove_unused_pokemon()
        return ret

    def remove_unused_pokemon(self):
        self.db.cursor.execute(
            'DELETE `up`'
            ' FROM `user_pokemon` `up`'
            '  LEFT JOIN `pokemon_battle` `b`'
            '   ON `b`.`user_pokemon_id`=`up`.`id`'
            '      OR `b`.`user_2_pokemon_id`=`up`.`id`'
            ' WHERE `up`.`user_id` IS NULL AND `b`.`id` IS NULL'
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
