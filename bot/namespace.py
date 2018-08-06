import argparse


class Namespace(argparse.Namespace):
    def __init__(self, prototype=None, **kwargs):
        super().__init__(**kwargs)
        self.prototype = prototype

    def has_own_property(self, prop):
        return prop in self.__dict__

    def __getattribute__(self, attr):
        try:
            return super().__getattribute__(attr)
        except AttributeError as ex:
            print(repr(ex))
            if self.prototype is None:
                raise
            return self.prototype.__getattribute__(attr)

    def __getitem__(self, item):
        try:
            return self.__dict__[item]
        except KeyError:
            if self.prototype is None:
                raise
            return self.prototype[item]
