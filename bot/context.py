import os
import json

from markovchain.text import MarkovText, ReplyMode
from markovchain.storage import SqliteStorage

from .error import CommandError
from .namespace import Namespace


class Context:
    PATH_SETTINGS = [
        'filter'
    ]

    def __init__(self, root, defaults):
        self.root = root
        self.name = os.path.basename(self.root)
        self.is_writable = not root.endswith('_ro')
        self.markov = MarkovText.from_file(
            os.path.join(self.root, 'markov.db'),
            storage=SqliteStorage
        )
        self.settings = self.load_settings(
            os.path.join(self.root, 'settings.json'),
            self.root,
            defaults
        )
        self.markov.save()

    def __str__(self):
        return self.name

    def get_orders(self):
        return self.markov.parser.state_sizes

    def random_text(self, order):
        return self.markov(state_size=order)

    def reply_text(self, text, order):
        return self.markov(
            state_size=order,
            reply_to=text,
            reply_mode=ReplyMode.REPLY
        )

    def learn_text(self, text):
        self.markov.data(text)
        self.markov.save()

    def random_sticker(self):
        raise CommandError('random_sticker: not implemented')

    def reply_sticker(self, sticker):
        raise CommandError('reply_sticker: not implemented')

    @classmethod
    def create(cls, root, settings):
        os.mkdir(root)
        with open(settings, 'rt') as fp:
            settings = json.load(fp)
        storage = SqliteStorage(
            settings=settings,
            db=os.path.join(root, 'markov.db')
        )
        markov = MarkovText.from_storage(storage)
        markov.save()
        storage.db.close()
        storage.db = None
        storage.cursor = None
        return cls(root, settings)

    @classmethod
    def load_settings(cls, fname, root, parent):
        try:
            with open(fname, 'rt') as fp:
                data = json.load(fp)
        except OSError:
            data = {}

        for item in cls.PATH_SETTINGS:
            try:
                data[item] = os.path.join(root, data[item])
            except KeyError:
                pass

        return Namespace(parent, **data)
