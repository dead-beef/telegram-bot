import re
import html

from pony.orm import select, count
from telegram import (
    ChatAction,
    TelegramError,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode
)
from telegram.error import BadRequest, Unauthorized

from bot.error import SearchError
from bot.models import get_page, SearchQuery, SearchLog
from bot.promise import Promise, PromiseType as PT
from bot.util import (
    remove_control_chars,
    get_command_args,
    send_image,
    command,
    CommandType as C,
    Permission as P
)


class SearchCommandMixin:
    RE_VIDEO_LINK = re.compile(r'^https?://(www\.)?youtube\.com\/')

    def __init__(self, bot):
        super().__init__(bot)
        self.help = self.help + (
            '\n'
            '/pic <query> - image search\n'
            '/vid <query> - video search\n'
            '/piclog - show image search log\n'
            '/picstats - show image search stats\n'
        )

    def _search(self, update, query, reset=False):
        chat = update.effective_chat
        chat_id = chat.id
        settings = self.state.get_chat_settings(chat)

        if update.callback_query:
            user = update.callback_query.from_user
            reply_to = None
        else:
            user = update.message.from_user
            reply_to = update.message.message_id

        primary_bot = self.state.bot.primary.bot
        if chat.type == chat.PRIVATE:
            bot = primary_bot
        else:
            bot = self.state.bot.updaters[-1].bot

        try:
            enabled = settings['search_enabled']
        except KeyError:
            enabled = False
        if not enabled:
            if reply_to is not None:
                primary_bot.send_message(
                    chat_id,
                    '"search_enabled": false',
                    quote=True,
                    reply_to_message_id=reply_to
                )
            return

        learn = Promise.wrap(
            self.state.learn_search_query,
            query, user, reset,
            ptype=PT.MANUAL
        )
        self.state.bot.queue.put(learn)
        learn.wait()
        offset = learn.value

        if isinstance(offset, Exception):
            self.logger.error(offset)
            return

        try:
            bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        except (Unauthorized, BadRequest) as ex:
            self.logger.warning('send_chat_action: %r', ex)
            try:
                primary_bot.send_message(
                    chat_id,
                    'add secondary bot to group',
                    quote=True,
                    reply_to_message_id=reply_to
                )
            except TelegramError as ex:
                self.logger.warning('send error message: %r', ex)
            return
        except TelegramError as ex:
            self.logger.error('send_chat_action: %r', ex)

        try:
            res, is_last = self.state.search(query, offset)
        except SearchError as ex:
            primary_bot.send_message(
                chat_id,
                str(ex),
                quote=True,
                reply_to_message_id=reply_to
            )
        except Exception as ex:
            primary_bot.send_message(
                chat_id,
                repr(ex),
                quote=True,
                reply_to_message_id=reply_to
            )
            return
        else:
            keyboard = [
                InlineKeyboardButton(
                    '\U0001f517 %d' % (offset + 1),
                    url=res.url
                )
            ]
            if offset >= 1:
                keyboard.append(
                    InlineKeyboardButton('reset', callback_data='picreset')
                )
            if not is_last:
                keyboard.append(
                    InlineKeyboardButton('next', callback_data='pic')
                )
            keyboard = InlineKeyboardMarkup([keyboard])

            if self.RE_VIDEO_LINK.match(res.url):
                bot.send_message(
                    chat_id,
                    '%s\n%s\n\n%s' % (res.title, res.url, query),
                    reply_markup=keyboard
                )
                return

            for url in (res.image, res.thumbnail, None):
                try:
                    self.logger.info('%r %r', query, url)
                    if url is None:
                        bot.send_message(
                            chat_id,
                            '(bad request)\n%s\n%s\n\n%s' % (
                                res.image, res.url, query
                            )
                        )
                    else:
                        send_image(
                            bot, chat_id, url,
                            caption=query,
                            reply_markup=keyboard
                        )
                    return
                except TelegramError as ex:
                    self.logger.info('image post failed: %r: %r', res, ex)

    @command(C.NONE, P.USER_2)
    def cmd_pic(self, _, update):
        query = get_command_args(update.message, help='usage: /pic <query>')
        query = remove_control_chars(query).replace('\n', ' ')
        self.state.run_async(self._search, update, query)

    @command(C.NONE, P.USER_2)
    def cmd_vid(self, _, update):
        query = get_command_args(update.message, help='usage: /vid <query>')
        query = remove_control_chars(query).replace('\n', ' ')
        query += ' site:youtube.com'
        self.state.run_async(self._search, update, query)

    @command(C.NONE, P.USER_2)
    def cb_pic(self, _, update):
        if not update.callback_query.message:
            self.logger.info('cb_pic no message')
        if update.callback_query.message.caption:
            query = update.callback_query.message.caption
        else:
            query = update.callback_query.message.text.split('\n\n')[-1]
        query = remove_control_chars(query)
        self.state.run_async(self._search, update, query)

    @command(C.NONE, P.USER_2)
    def cb_picreset(self, _, update):
        if not update.callback_query.message:
            self.logger.info('cb_picreset no message')
        if update.callback_query.message.caption:
            query = update.callback_query.message.caption
        else:
            query = update.callback_query.message.text.split('\n\n')[-1]
        query = remove_control_chars(query)
        self.state.run_async(self._search, update, query, True)

    @command(C.REPLY_TEXT_PAGINATED, P.USER_2)
    def cmd_piclog(self, _, update):
        page_size = 10
        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1
        offset = page_size * (page - 1)
        requests, pages = get_page(SearchLog.select(), page, page_size)
        res = '\n'.join(
            '{0}. {1} (<b>{2}</b>)'
            .format(
                i,
                html.escape(data.query.query),
                html.escape(data.user.name)
            )
            for i, data in enumerate(requests, offset + 1)
        )
        res = 'pic log page %d / %d:\n\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.HTML

    cb_pic_log = cmd_piclog

    @command(C.REPLY_TEXT_PAGINATED, P.USER_2)
    def cmd_picstats(self, _, update):
        page_size = 10
        if update.callback_query:
            page = int(update.callback_query.data)
        else:
            page = 1
        query = select((q, count(log)) for q in SearchQuery for log in q.log)
        query = query.order_by(-2)
        stats, pages = get_page(query, page, page_size)
        offset = page_size * (page - 1)
        res = '\n'.join(
            '{0}. {1} (<b>{2}</b>)'
            .format(i, html.escape(query.query), count)
            for i, (query, count) in enumerate(stats, offset + 1)
        )
        res = 'pic stats page %d / %d:\n\n%s' % (page, pages, res)
        return res, page, pages, False, ParseMode.HTML

    cb_pic_stats = cmd_picstats
