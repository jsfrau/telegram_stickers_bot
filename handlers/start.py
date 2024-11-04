# handlers/start.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from tg_stickers_bot.database import add_user, is_admin, get_public_packs
from .admin import admin_panel
from .create import create_new_pack, PROCESSING_STICKERS
from tg_stickers_bot.handlers.edit import edit_pack
from .delete import delete_pack, confirm_delete_pack
from telegram.ext import ContextTypes, ConversationHandler
from tg_stickers_bot.states import CHOOSING_ACTION, PROCESSING_STICKERS, ADMIN_PANEL
from tg_stickers_bot.utils import log_error
import traceback

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user = update.effective_user
        add_user(user.id, user.username or user.full_name)

        keyboard = [
            [InlineKeyboardButton("Создать новый стикерпак", callback_data='create_new')],
            [InlineKeyboardButton("Редактировать стикерпак", callback_data='edit_pack')],
            [InlineKeyboardButton("Удалить стикерпак", callback_data='delete_pack')],
            [InlineKeyboardButton("Просмотреть публичные стикерпакеты", callback_data='view_public_packs')],
            [InlineKeyboardButton("О боте", callback_data='about')]
        ]

        if is_admin(user.id):
            keyboard.insert(0, [InlineKeyboardButton("Админ панель", callback_data='admin_panel')])

        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text('Добро пожаловать! Выберите действие:', reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.edit_message_text('Добро пожаловать! Выберите действие:', reply_markup=reply_markup)
        return CHOOSING_ACTION
    except Exception as e:
        log_error(f"Ошибка в start: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при запуске бота.')
        return ConversationHandler.END

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()

        if query.data == 'about':
            await query.edit_message_text('Этот бот создает стикерпаки из ваших изображений.')
            return ConversationHandler.END
        elif query.data == 'create_new':
            await create_new_pack(update, context)
            return PROCESSING_STICKERS
        elif query.data == 'edit_pack':
            await edit_pack(update, context)
            return ConversationHandler.END
        elif query.data == 'delete_pack':
            await delete_pack(update, context)
            return ConversationHandler.END
        elif query.data == 'view_public_packs':
            await view_public_packs(update, context)
            return ConversationHandler.END
        elif query.data == 'admin_panel':
            await admin_panel(update, context)
            return ADMIN_PANEL
        else:
            await query.edit_message_text('Неизвестная команда.')
            return ConversationHandler.END
    except Exception as e:
        log_error(f"Ошибка в button_callback: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при обработке кнопки.')
        return ConversationHandler.END

async def view_public_packs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        packs = context.bot_data.get('public_packs', [])
        if not packs:
            # Получаем публичные стикерпакеты из базы данных
            packs = get_public_packs()
            context.bot_data['public_packs'] = packs  # Кэшируем для будущих запросов

        if not packs:
            await update.callback_query.edit_message_text('Публичных стикерпаков нет.')
            return

        keyboard = [
            [InlineKeyboardButton(f"{pack[1]}", url=pack[3])]  # pack[3] = pack_link
            for pack in packs
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text('Публичные стикерпакеты:', reply_markup=reply_markup)
    except Exception as e:
        log_error(f"Ошибка в view_public_packs: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при отображении публичных стикерпаков.')
