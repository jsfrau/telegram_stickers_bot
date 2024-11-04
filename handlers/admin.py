from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_users, get_user_packs, get_pack_by_id, delete_sticker_pack, get_all_packs
from handlers import start
from utils import log_error
import traceback
from states import ADMIN_PANEL, ADMIN_USER_LIST, ADMIN_PACK_LIST, ADMIN_PACK_ACTION, CHOOSING_ACTION, ADMIN_ALL_PACKS, \
    ADMIN_ALL_PACK_ACTION


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        keyboard = [
            [InlineKeyboardButton("Пользователи", callback_data='admin_users')],
            [InlineKeyboardButton("Все стикерпаки", callback_data='admin_all_packs')],
            [InlineKeyboardButton("Доступ к набору по имени", callback_data='admin_access_pack')],
            [InlineKeyboardButton("Назад", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text('Админ панель:', reply_markup=reply_markup)
        return ADMIN_PANEL
    except Exception as e:
        log_error(f"Ошибка в admin_panel: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка в админ панели.')
        return ConversationHandler.END


async def admin_panel_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == 'admin_users':
        return await admin_users(update, context)
    elif query.data == 'admin_all_packs':
        return await admin_all_packs(update, context)
    elif query.data == 'admin_access_pack':
        await query.edit_message_text('Функционал доступа к набору по имени пока не реализован.')
        return ADMIN_PANEL
    elif query.data == 'back_to_main':
        from .start import start
        await start(update, context)
        return CHOOSING_ACTION
    else:
        await query.edit_message_text('Неизвестная команда.')
        return ADMIN_PANEL

async def admin_all_packs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()

        page = context.user_data.get('admin_all_packs_page', 0)
        packs = get_all_packs(offset=page * 10, limit=10)

        if not packs:
            await query.edit_message_text('Нет стикерпаков для отображения.')
            return ADMIN_PANEL

        keyboard = []
        for pack in packs:
            keyboard.append([InlineKeyboardButton(f"{pack[1]} (ID: {pack[0]})", callback_data=f'admin_all_pack_{pack[0]}')])

        pagination_buttons = []
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("<", callback_data='admin_all_packs_prev'))
        if len(packs) == 10:
            pagination_buttons.append(InlineKeyboardButton(">", callback_data='admin_all_packs_next'))
        if pagination_buttons:
            keyboard.append(pagination_buttons)

        keyboard.append([InlineKeyboardButton("Назад", callback_data='admin_panel')])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('Список всех стикерпаков:', reply_markup=reply_markup)
        return ADMIN_ALL_PACKS
    except Exception as e:
        log_error(f"Ошибка в admin_all_packs: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при отображении списка стикерпаков.')
        return ConversationHandler.END

async def admin_all_packs_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    action = query.data
    page = context.user_data.get('admin_all_packs_page', 0)

    if action == 'admin_all_packs_next':
        context.user_data['admin_all_packs_page'] = page + 1
    elif action == 'admin_all_packs_prev' and page > 0:
        context.user_data['admin_all_packs_page'] = page - 1

    return await admin_all_packs(update, context)


async def admin_all_pack_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    try:
        pack_id = int(query.data.split('_')[3])
    except (IndexError, ValueError):
        await query.edit_message_text('Некорректный идентификатор стикерпака.')
        return ADMIN_ALL_PACKS

    context.user_data['selected_pack_id'] = pack_id

    pack = get_pack_by_id(pack_id)
    if not pack:
        await query.edit_message_text('Стикерпак не найден.')
        return ADMIN_ALL_PACKS

    pack_link = pack[4]  # Предполагая, что pack_link находится в индексе 4
    keyboard = [
        [InlineKeyboardButton("Удалить стикерпак", callback_data='admin_all_delete_pack')],
        [InlineKeyboardButton("Назад", callback_data='admin_all_packs')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f'Стикерпак:\n{pack_link}', reply_markup=reply_markup)
    return ADMIN_ALL_PACK_ACTION


async def admin_all_delete_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    pack_id = context.user_data.get('selected_pack_id')
    if not pack_id:
        await query.edit_message_text('Не выбран стикерпак для удаления.')
        return ADMIN_ALL_PACK_ACTION

    pack = get_pack_by_id(pack_id)
    if not pack:
        await query.edit_message_text('Стикерпак не найден.')
        return ADMIN_ALL_PACK_ACTION

    user_id = pack[1]  # Предполагая, что user_id находится в индексе 1

    bot = context.bot
    success = await delete_sticker_pack(pack_id, None, bot)  # Передаем user_id=None

    if success:
        await query.edit_message_text(f'Стикерпак с ID {pack_id} успешно удален.')
    else:
        await query.edit_message_text('Не удалось удалить стикерпак.')

    return ADMIN_ALL_PACKS



async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()

        page = context.user_data.get('admin_user_page', 0)
        users = get_users(offset=page * 10, limit=10)

        if not users:
            await query.edit_message_text('Нет пользователей для отображения.')
            return ADMIN_PANEL

        keyboard = []
        for user in users:
            keyboard.append([InlineKeyboardButton(f"{user[1]} (ID: {user[0]})", callback_data=f'admin_user_{user[0]}')])

        pagination_buttons = []
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("<", callback_data='admin_users_prev'))
        if len(users) == 10:
            pagination_buttons.append(InlineKeyboardButton(">", callback_data='admin_users_next'))
        if pagination_buttons:
            keyboard.append(pagination_buttons)

        keyboard.append([InlineKeyboardButton("Назад", callback_data='admin_panel')])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('Список пользователей:', reply_markup=reply_markup)
        return ADMIN_USER_LIST
    except Exception as e:
        log_error(f"Ошибка в admin_users: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при отображении списка пользователей.')
        return ConversationHandler.END

async def admin_users_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    action = query.data
    page = context.user_data.get('admin_user_page', 0)

    if action == 'admin_users_next':
        context.user_data['admin_user_page'] = page + 1
    elif action == 'admin_users_prev' and page > 0:
        context.user_data['admin_user_page'] = page - 1

    return await admin_users(update, context)

async def admin_user_packs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    try:
        user_id = int(query.data.split('_')[2])
    except (IndexError, ValueError):
        await query.edit_message_text('Некорректный идентификатор пользователя.')
        return ADMIN_USER_LIST

    context.user_data['selected_user_id'] = user_id

    packs = get_user_packs(user_id)

    if not packs:
        await query.edit_message_text('У пользователя нет стикерпаков.')
        return ADMIN_USER_LIST

    keyboard = []
    for pack in packs:
        keyboard.append([InlineKeyboardButton(f"{pack[1]} (ID: {pack[0]})", callback_data=f'admin_pack_{pack[0]}')])

    keyboard.append([InlineKeyboardButton("Назад", callback_data='admin_users')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Стикерпаки пользователя:', reply_markup=reply_markup)
    return ADMIN_PACK_LIST

async def admin_pack_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    try:
        pack_id = int(query.data.split('_')[2])
    except (IndexError, ValueError):
        await query.edit_message_text('Некорректный идентификатор стикерпака.')
        return ADMIN_PACK_LIST

    context.user_data['selected_pack_id'] = pack_id

    pack = get_pack_by_id(pack_id)
    if not pack:
        await query.edit_message_text('Стикерпак не найден.')
        return ADMIN_PACK_LIST

    pack_link = pack[4]  # Предполагая, что pack_link находится в индексе 4
    keyboard = [
        [InlineKeyboardButton("Удалить стикерпак", callback_data='admin_delete_pack')],
        [InlineKeyboardButton("Назад", callback_data='admin_user_packs')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f'Стикерпак:\n{pack_link}', reply_markup=reply_markup)
    return ADMIN_PACK_ACTION

async def admin_delete_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    pack_id = context.user_data.get('selected_pack_id')
    if not pack_id:
        await query.edit_message_text('Не выбран стикерпак для удаления.')
        return ADMIN_PACK_ACTION

    pack = get_pack_by_id(pack_id)
    if not pack:
        await query.edit_message_text('Стикерпак не найден.')
        return ADMIN_PACK_ACTION

    user_id = pack[1]  # Предполагая, что user_id находится в индексе 1

    bot = context.bot
    success = await delete_sticker_pack(pack_id, user_id, bot)

    if success:
        await query.edit_message_text(f'Стикерпак с ID {pack_id} успешно удален.')
    else:
        await query.edit_message_text('Не удалось удалить стикерпак.')

    return ADMIN_PACK_LIST
