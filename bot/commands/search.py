from telegram import (
    ChatAction,
    TelegramError,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.error import BadRequest, Unauthorized

from bot.error import SearchError
from bot.promise import Promise, PromiseType as PT
from bot.util import (
    remove_control_chars,
    get_command_args,
    send_image,
    command,
    CommandType as C
)


class SearchCommandMixin:
    def __init__(self, bot):
        super().__init__(bot)
        self.help = self.help + (
            '\n'
            '/pic <query> - image search\n'
            '/piclog - show image search log\n'
            '/picstats - show image search stats\n'
        )

    def _search(self, update, query, reset=False):
        if update.callback_query:
            user = update.callback_query.from_user
            reply_to = None
        else:
            user = update.message.from_user
            reply_to = update.message.message_id

        learn = Promise.wrap(
            self.state.db.learn_search_query,
            query, user, reset,
            ptype=PT.MANUAL
        )
        self.state.bot.queue.put(learn)
        learn.wait()
        offset = learn.value

        chat = update.effective_chat
        chat_id = chat.id

        primary_bot = self.state.bot.primary.bot
        if chat.type == chat.PRIVATE:
            bot = primary_bot
        else:
            bot = self.state.bot.updaters[-1].bot

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

    @command(C.NONE)
    def cmd_pic(self, _, update):
        query = get_command_args(update.message, help='usage: /pic <query>')
        query = remove_control_chars(query).replace('\n', ' ')
        self.state.run_async(self._search, update, query)

    @command(C.NONE)
    def cb_pic(self, _, update):
        if not update.callback_query.message:
            self.logger.info('cb_pic no message')
        query = remove_control_chars(update.callback_query.message.caption)
        self.state.run_async(self._search, update, query)

    @command(C.NONE)
    def cb_picreset(self, _, update):
        if not update.callback_query.message:
            self.logger.info('cb_picreset no message')
        query = remove_control_chars(update.callback_query.message.caption)
        self.state.run_async(self._search, update, query, True)

    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_piclog(self, _, update):
        return self.state.list_search_requests(update)

    @command(C.REPLY_TEXT_PAGINATED)
    def cb_pic_log(self, *_):
        return self.state.list_search_requests

    @command(C.REPLY_TEXT_PAGINATED)
    def cmd_picstats(self, _, update):
        return self.state.get_search_stats(update)

    @command(C.REPLY_TEXT_PAGINATED)
    def cb_pic_stats(self, *_):
        return self.state.get_search_stats
