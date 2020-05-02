import sys
import json
import time

from tqdm import tqdm
from pony.orm import db_session, select

from .models import connect, flush, Chat, User, Message


def get_chat_id(msg):
    try:
        return next(iter(msg['to'].values()))
    except (KeyError, StopIteration):
        return None

def get_chat(src, chat_id):
    for chat in src['chats']:
        if chat['id'] == chat_id:
            return chat
    return None

def get_user(src, user_id):
    for user in src['users']:
        if user['id'] == user_id:
            return user
    return None

def main(argv):
    if len(argv) not in (4, 5):
        print('usage: python -m bot.import_json <src_json> <src_chat_id> <dst_db> [dst_chat_id]', file=sys.stderr)
        return 1

    connect(argv[3])

    with db_session:
        src_chat_id = int(argv[2])
        create_dst_chat = False

        if len(argv) > 4:
            dst_chat_id = int(argv[4])
        else:
            dst_chat_id = src_chat_id
            create_dst_chat = True

        chat = Chat.get(id=dst_chat_id)

        if chat is None and not create_dst_chat:
            print('no chat with id "%s" in database' % dst_chat_id)
            return 1

        print('loading json...')
        with open(argv[1], 'rt') as fp:
            src = json.load(fp)

        src_chat = get_chat(src, src_chat_id)
        src_user = get_user(src, src_chat_id)

        if src_chat is not None:
            print('found chat %r' % src_chat)
        if src_user is not None:
            print('found user %r' % src_user)

        if src_chat is not None and src_user is not None:
            print('ambiguous chat id')
            return 1
        if src_chat is None and src_user is None:
            print('no chat with id "%s" in json' % src_chat_id)
            return 1

        if chat is None and create_dst_chat:
            print('creating chat...')
            if src_chat is not None:
                print('create chat %r' % src_chat)
                chat = Chat(
                    id=src_chat['id'],
                    title=src_chat['title'],
                    username=src_chat.get('username'),
                    type='group',
                    last_update=-1
                )
            else:
                print('create user chat %r' % src_user)
                chat = Chat(
                    id=src_user['id'],
                    first_name=src_user.get('first_name'),
                    last_name=src_user.get('last_name'),
                    username=src_user.get('username'),
                    type='private',
                    last_update=-1
                )

        print('\nloading users...')
        loaded = 0
        exists = 0
        for user in src['users']:
            u = User.get(id=int(user['id']))
            if u is None:
                loaded += 1
                User(
                    id=int(user['id']),
                    first_name=user.get('first_name', None),
                    last_name=user.get('last_name', None),
                    username=user.get('username', None),
                    last_update=int(time.time())
                )
            else:
                exists += 1
        flush()
        print('loaded %d, exists %d' % (loaded, exists))

        loaded = 0
        exists = 0
        skip = 0
        print('\nloading messages...')
        has_message = set(select(
            m.id_in_chat for m in Message if m.chat == chat
        ))
        for msg in tqdm(src['messages']):
            if get_chat_id(msg) != src_chat_id:
                skip += 1
                continue
            if msg['id'] in has_message:
                exists += 1
                continue
            loaded += 1
            user_id = msg['from_id']
            if user_id == 0:
                user_id = None
            text = (
                msg.get('message', None)
                or msg.get('text', None)
                or msg.get('caption', None)
                or msg.get('title', None)
                or msg.get('description', None)
                or msg.get('alt', None)
            )
            if 'sticker_set_id' in msg:
                sticker_id = msg.get('file_reference', None)
                file_id = None
            else:
                file_id = msg.get('file_reference', None)
                sticker_id = None
            file_name = msg.get('file_name', None)
            Message(
                chat=chat,
                id_in_chat=msg['id'],
                user=user_id,
                timestamp=msg['date'],
                text=text,
                sticker_id=sticker_id,
                file_id=file_id,
                file_name=file_name
            )
        print('loaded %d, exists %d, skip %d' % (loaded, exists, skip))
        print('\ncommitting...')

    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
