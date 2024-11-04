from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_user_packs, delete_sticker_pack
from utils import log_error
import traceback

async def delete_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = update.callback_query
        await query.answer()

        user_packs = get_user_packs(update.effective_user.id)
        if not user_packs:
            await query.edit_message_text('У вас нет стикерпаков для удаления.')
            return

        keyboard = [
            [InlineKeyboardButton(f"{pack[1]} (ID: {pack[0]})", callback_data=f'delete_{pack[0]}')]
            for pack in user_packs
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('Выберите стикерпак для удаления:', reply_markup=reply_markup)
    except Exception as e:
        log_error(f"Ошибка в delete_pack: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при отображении списка стикерпаков.')



async def confirm_delete_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = update.callback_query
        await query.answer()

        # Извлекаем pack_id из callback_data, которая имеет формат 'delete_<pack_id>'
        try:
            pack_id = int(query.data.split('_')[1])
        except (IndexError, ValueError):
            await query.edit_message_text('Некорректный идентификатор стикерпака.')
            return

        # Получаем экземпляр Bot из контекста
        bot = context.bot

        # Вызываем функцию удаления стикерпака
        success = await delete_sticker_pack(pack_id, update.effective_user.id, bot)

        if success:
            await query.edit_message_text(f'Стикерпак с ID {pack_id} успешно удален.')
        else:
            await query.edit_message_text(
                'Не удалось удалить стикерпак. Убедитесь, что стикерпак существует и принадлежит вам.')
    except Exception as e:
        log_error(f"Ошибка в confirm_delete_pack: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при удалении стикерпака.')