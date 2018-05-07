import os
import sys
import logging
from argparse import ArgumentParser

from .bot import Bot
from .util import configure_logger


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
        '-m', '--message-log',
        metavar='FILE',
        default=None,
        help=('message log file ("-" - stdout,'
              ' "none" - disable message logging)'
              ' (default: <bot directory>/messages.log)')
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

    if args.message_log == '-':
        args.message_log = sys.stdout

    if os.path.isfile(args.token):
        with open(args.token, 'r') as fp:
            args.token = fp.read()

    args.log_level = getattr(logging, args.log_level.upper())
    args.log_messages = args.message_log != 'none'

    logging.basicConfig(
        level=args.log_level,
        format=Bot.LOG_FORMAT
    )

    bot = Bot(
        args.token,
        proxy=args.proxy,
        root=args.data_dir,
        log_messages=args.log_messages
    )

    if args.message_log is None:
        args.message_log = os.path.join(bot.state.root, 'messages.log')

    if args.log_messages:
        configure_logger(
            'bot.message',
            log_file=args.message_log,
            log_format=Bot.MSG_LOG_FORMAT,
            log_level=logging.INFO
        )

    try:
        bot.start_polling(args.poll)
    finally:
        logging.shutdown()
