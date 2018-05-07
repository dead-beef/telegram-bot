import os
import json

from markovchain.text import MarkovText, ReplyMode
from markovchain.storage import SqliteStorage

from .error import CommandError


class Context:
    def __init__(self, root):
        self.root = root
        self.name = os.path.basename(self.root)
        self.is_writable = not root.endswith('_ro')
        self.markov = MarkovText.from_file(
            os.path.join(self.root, 'markov.db'),
            storage=SqliteStorage
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
        return cls(root)
