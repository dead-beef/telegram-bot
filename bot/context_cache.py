import os
import shutil

from .context import Context


class ContextCache:
    def __init__(self, root):
        self.root = os.path.join(root, 'public')
        self.root_private = os.path.join(root, 'private')
        self.root_settings = os.path.join(root, '..', 'settings')
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(self.root_private, exist_ok=True)
        os.makedirs(self.root_settings, exist_ok=True)
        self.context = {}
        self.defaults = Context.load_settings(
            os.path.join(self.root_settings, 'default.json'),
            self.root_settings,
            None
        )

    def __contains__(self, name):
        return name in self.context

    def load(self, name):
        raise NotImplementedError('context load')

    def get_path(self, name):
        ret = os.path.join(self.root, name)
        if os.path.isdir(ret):
            return ret, False
        ret = os.path.join(self.root_private, name)
        if os.path.isdir(ret):
            return ret, True
        raise FileNotFoundError('context not found: "%s"' % name)

    def create_private(self, name):
        if name in self:
            raise ValueError('context exists: %s' % name)
        ret = Context.create(
            os.path.join(self.root_private, name),
            os.path.join(self.root_settings, 'markov.json')
        )
        self.context[name] = ret
        return ret

    def has_private(self, chat):
        name = str(chat.id)
        return os.path.isdir(os.path.join(self.root_private, name))

    def delete_private(self, chat):
        name = str(chat.id)
        shutil.rmtree(os.path.join(self.root_private, name))
        try:
            del self.context[name]
        except KeyError:
            pass

    def get(self, name):
        if name is None:
            return None
        try:
            return self.context[name]
        except KeyError:
            path, private = self.get_path(name)
            ctx = Context(path, self.defaults, private)
            self.context[name] = ctx
            return ctx

    def get_private(self, chat):
        name = str(chat.id)
        try:
            return self.get(name)
        except FileNotFoundError:
            return self.create_private(name)

    def list(self, chat_id=None):
        ret = [
            fname
            for fname in os.listdir(self.root)
            if os.path.isdir(os.path.join(self.root, fname))
        ]
        if chat_id is not None:
            chat_id = str(chat_id)
            private = os.path.join(self.root_private, chat_id)
            if os.path.isdir(private):
                ret.append(chat_id)
            else:
                ret.append('new private context')
        return ret
