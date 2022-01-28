import os
import logging
from argparse import ArgumentParser

from .bot import Bot
from .util import get_tokens


def create_arg_parser():
    parser = ArgumentParser()
    parser.add_argument(
        '-P', '--poll',
        type=float, default=0.0,
        help='polling interval in seconds (default: %(default)s)'
    )
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
        '-l', '--log-level',
        default='info',
        choices=('critical', 'error', 'warning', 'info', 'debug'),
        help='log level (default: %(default)s)'
    )
    parser.add_argument(
        'token',
        metavar='TOKEN_OR_FILE',
        help='bot token or token file'
    )
    return parser


def main(args=None):
    parser = create_arg_parser()
    args = parser.parse_args(args)

    args.token = get_tokens(args.token)

    args.proxy = args.proxy.strip()
    if not args.proxy or args.proxy.lower() == 'none':
        args.proxy = None

    args.log_level = getattr(logging, args.log_level.upper())

    logging.basicConfig(
        level=args.log_level,
        format=Bot.LOG_FORMAT
    )

    bot = Bot(
        args.token,
        proxy=args.proxy,
        root=args.data_dir
    )

    try:
        bot.start_polling(args.poll)
    finally:
        logging.shutdown()
