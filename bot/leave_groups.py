import os
import sys

from time import sleep

from argparse import ArgumentParser

from telegram import Bot
from telegram.error import TelegramError, RetryAfter, BadRequest
from telegram.utils.request import Request

from tqdm import tqdm
from pony.orm import db_session

from .models import connect, get_db_path, Chat
from .util import get_tokens


def main(args=None):
    parser = ArgumentParser()
    parser.add_argument(
        '-p', '--proxy',
        default='socks5://127.0.0.1:9050/',
        help='proxy (default: %(default)s (tor))'
    )
    parser.add_argument(
        '-d', '--data-dir',
        default=os.path.expanduser('~/.bot'),
        help='bot data directory (default: %(default)s)'
    )
    parser.add_argument(
        'token',
        metavar='TOKEN_OR_FILE',
        help='bot token or token file'
    )

    args = parser.parse_args(args)

    if args.proxy.lower() in ['-', 'none']:
        args.proxy = None
    db_path = get_db_path(args.data_dir)
    tokens = get_tokens(args.token)

    bots = [
        Bot(token, request=Request(proxy_url=args.proxy))
        for token in tokens
    ]

    print('get_me: %s' % ' '.join('@' + bot.get_me().username for bot in bots))

    connect(db_path)

    with db_session:
        chats = Chat.select(
            lambda c: c.type in ('group', 'supergroup', 'private')
        )
        count = len(chats)
        left = 0
        errors = 0
        print('trying to leave %d groups' % count)
        for chat in tqdm(chats):
            while True:
                try:
                    res = all(bot.leave_chat(chat.id) for bot in bots)
                    left += int(res)
                    break
                except BadRequest:
                    break
                except RetryAfter as ex:
                    sleep(ex.retry_after)
                except TelegramError as ex:
                    print(
                        'error leaving group %r (%r): %r'
                        % (chat.title, chat.id, ex)
                    )
                    errors += 1
                    break
        print('left %d / %d groups, %d errors' % (left, count, errors))

    return 0

if __name__ == '__main__':
    sys.exit(main())
