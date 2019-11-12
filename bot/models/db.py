import math
import time
import pony.orm
import pony.orm.dbproviders.sqlite

try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3


def patch_sqlite_provider(module):
    module.sqlite = sqlite3
    module.SQLiteTranslator.sqlite_version = sqlite3.sqlite_version_info
    module.SQLiteProvider.server_version = sqlite3.sqlite_version_info

patch_sqlite_provider(pony.orm.dbproviders.sqlite)
db = pony.orm.Database()

@db.on_connect(provider='sqlite')
def sqlite_config(_, connection):
    cursor = connection.cursor()
    cursor.execute('PRAGMA case_sensitive_like=0')
    cursor.execute('PRAGMA foreign_keys=1')


def get_page(query, page, page_size):
    pages = math.ceil(len(query) / page_size)
    res = query[(page - 1) * page_size:page * page_size]
    return res, pages

def get_or_create(cls, id_, **kwargs):
    ret = cls.get(id=id_)
    if ret is None:
        ret = cls(id=id_, **kwargs)
    return ret

def update_or_create(cls, id_, interval=None, **kwargs):
    ret = cls.get(id=id_)
    current_time = int(time.time())
    if interval is not None:
        kwargs['last_update'] = current_time

    if ret is None:
        return cls(id=id_, **kwargs)

    if interval is not None:
        if interval <= 0 or current_time - ret.last_update < interval:
            return ret

    for key, val in kwargs.items():
        setattr(ret, key, val)
    return ret
