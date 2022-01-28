import re
import random

from base64 import b64encode, b64decode

import dice

from telegram import (
    ParseMode
)

from bot.safe_eval import safe_eval
from bot.promise import Promise
from bot.util import (
    get_file,
    get_command_args,
    strip_command,
    command,
    CommandType as C
)


class MiscCommandMixin:
    RE_DICE = re.compile(r'^\s*([0-9d][-+0-9duwtfrF%hml^ov ]*)')

    def __init__(self, bot):
        super().__init__(bot)
        self.help = self.help + (
            '\n'
            '/help - bot help\n'
            '/helptags - list formatter tags\n'
            '/helpemotes - list formatter emotes\n'
            '\n'
            '/b64 <text> - encode base64\n'
            '/b64d <base64> - decode base64\n'
            '/echo <text> - print text\n'
            '/eval <expression> - evaluate expression\n'
            '/format <text> - format text\n'
            '/getfile - get file from message\n'
            '/roll <dice> [message] - roll dice\n'
            '/start - generate text\n'
            '/image - generate image\n'
            '/ocr [language[+language...]] - ocr\n'
            '/sticker - send random sticker\n'
            '/makesticker - create sticker from image'
        )

    @command(C.REPLY_TEXT)
    def cmd_start(self, _, update):
        return self.state.random_text(update)

    @command(C.REPLY_TEXT)
    def cmd_image(self, _, update):
        msg = update.message
        if msg.photo:
            pass
        elif msg.reply_to_message and msg.reply_to_message.photo:
            msg = msg.reply_to_message
        else:
            update.message.reply_text('no input image')
            return None
        return self.state.on_photo(update, msg, True)

    @command(C.NONE)
    def cmd_ocr(self, _, update):
        msg = update.message
        args = strip_command(msg.text)

        if args and not re.match(r'^[a-z]{3}([+_][a-z]{3})*$', args):
            update.message.reply_text('invalid language %r' % args)
            return

        if msg.photo:
            pass
        elif msg.reply_to_message and msg.reply_to_message.photo:
            msg = msg.reply_to_message
        else:
            update.message.reply_text('no input image')
            return

        deferred = Promise.defer()
        self.state.bot.download_file(msg, self.state.file_dir, deferred)
        self.state.run_async(self._run_script, update,
                             'ocr', [args], deferred.promise, 'no text found')

    @command(C.NONE)
    def cmd_makesticker(self, _, update):
        msg = update.message
        if msg.photo or msg.document:
            pass
        elif msg.reply_to_message and (
                msg.reply_to_message.photo
                or msg.reply_to_message.document
        ):
            msg = msg.reply_to_message
        else:
            update.message.reply_text('no input image')
            return

        deferred = Promise.defer()
        self.state.bot.download_file(msg, self.state.file_dir, deferred)
        self.state.run_async(
            self._run_script, update,
            'make_sticker', ['{{TMP}}'],
            deferred.promise,
            return_file='png',
            timeout=self.state.query_timeout
        )

    @command(C.NONE)
    def cmd_getfile(self, _, update):
        msg = update.message
        try:
            ftype, _ = get_file(msg)
        except ValueError:
            try:
                msg = msg.reply_to_message
                ftype, _ = get_file(msg)
            except (AttributeError, ValueError):
                update.message.reply_text('no input file', quote=True)
                return

        if ftype == 'sticker':
            convert = 'unmake_sticker'
            ext = 'png'
        #elif ftype == 'video_note':
        #    convert = 'unmake_video'
        #    ext = ''
        #elif ftype == 'voice':
        #    convert = 'unmake_voice'
        #    ext = ''
        else:
            update.message.reply_text(
                'file type "%s" is not supported' % ftype,
                quote=True
            )
            return

        deferred = Promise.defer()
        self.state.bot.download_file(msg, self.state.file_dir, deferred)
        self.state.run_async(
            self._run_script, update,
            convert, ['{{TMP}}'],
            deferred.promise,
            return_file=ext,
            timeout=self.state.query_timeout
        )

    @command(C.REPLY_STICKER)
    def cmd_sticker(self, *_):
        return self.state.random_sticker(), True

    @command(C.REPLY_TEXT)
    def cmd_help(self, *_):
        return self.help

    @command(C.REPLY_TEXT)
    def cmd_helptags(self, *_):
        return self.formatter_tags, True, ParseMode.HTML

    @command(C.REPLY_TEXT)
    def cmd_helpemotes(self, *_):
        return self.formatter_emotes

    @command(C.NONE)
    def cmd_echo(self, bot, update):
        msg = get_command_args(update.message, help='usage: /echo <text>')
        bot.send_message(chat_id=update.message.chat_id, text=msg)

    @command(C.REPLY_TEXT)
    def cmd_roll(self, _, update):
        help_ = ('usage:\n'
                 '/roll <dice> [message]\n'
                 '/roll <string> || <string> [|| <string>...]\n')
        msg = get_command_args(update.message, help=help_)
        match = self.RE_DICE.match(msg)
        if match is None:
            settings = self.state.get_chat_settings(update.message.chat)
            separator = settings['roll_separator']
            strings = [s for s in re.split(separator, msg, re.I) if s]
            if len(strings) < 2:
                return help_, True
            return random.choice(strings), True
        msg = match.group(1).strip()
        roll = int(dice.roll(msg))
        return (
            '<i>%s</i> → <b>%s</b>' % (msg, roll),
            True, ParseMode.HTML
        )

    @command(C.REPLY_TEXT)
    def cmd_format(self, _, update):
        msg = get_command_args(update.message, help='usage: /format <text>')
        msg = self.state.formatter.format(msg)
        return msg, True, ParseMode.HTML

    @command(C.REPLY_TEXT)
    def cmd_eval(self, _, update):
        msg = get_command_args(update.message, help='usage: /eval <expression>')
        msg = safe_eval(msg)
        msg = re.sub(r'\.?0+$', '', '%.04f' % msg)
        return msg, True

    @command(C.REPLY_TEXT)
    def cmd_b64(self, _, update):
        msg = get_command_args(update.message, help='usage: /b64 <text>')
        msg = b64encode(msg.encode('utf-8')).decode('ascii')
        return msg, True

    @command(C.NONE)
    def cmd_b64d(self, bot, update):
        msg = get_command_args(update.message, help='usage: /b64d <base64>')
        msg = b64decode(msg.encode('utf-8'), validate=True).decode('utf-8')
        bot.send_message(chat_id=update.message.chat_id, text=msg)
