# handlers/edit.py
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from tg_stickers_bot.database import get_user_packs, get_pack_by_id, update_pack_name, replace_stickers
from tg_stickers_bot.states import EDITING_PHOTOS, AWAITING_PACK_NAME, PROCESSING_MEDIA
from tg_stickers_bot.utils import log_error
import traceback

from tg_stickers_bot.handlers.create import prepare_stickers_for_pack, is_english, \
    process_image_variants, process_video_variants, \
    show_current_media_selection_menu  # Импортируем функцию создания стикерпаков

async def edit_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_packs = get_user_packs(update.effective_user.id)
    if not user_packs:
        await query.edit_message_text('У вас нет стикерпаков для редактирования.')
        return

    keyboard = [
        [InlineKeyboardButton(f"{pack[1]} (ID: {pack[0]})", callback_data=f'edit_{pack[0]}')]
        for pack in user_packs
    ]
    keyboard.append([InlineKeyboardButton("Назад", callback_data='back_to_main')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text('Выберите стикерпак для редактирования:', reply_markup=reply_markup)

    return EDITING_PHOTOS

async def edit_pack_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    try:
        pack_id = int(query.data.split('_')[1])
    except (IndexError, ValueError):
        await query.edit_message_text('Некорректный идентификатор стикерпака.')
        return EDITING_PHOTOS

    pack = get_pack_by_id(pack_id)
    if not pack:
        await query.edit_message_text('Стикерпак не найден.')
        return EDITING_PHOTOS

    context.user_data['selected_pack_id'] = pack_id

    keyboard = [
        [InlineKeyboardButton("Изменить название", callback_data='edit_pack_name')],
        [InlineKeyboardButton("Заменить стикеры", callback_data='replace_stickers')],
        [InlineKeyboardButton("Удалить стикерпак", callback_data='delete_pack')],
        [InlineKeyboardButton("Назад", callback_data='edit_pack')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f'Редактирование стикерпака: {pack[2]}', reply_markup=reply_markup)
    return EDITING_PHOTOS

async def handle_edit_pack_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.edit_message_text('Введите новое название для стикерпака:')
    return AWAITING_PACK_NAME  # Определите соответствующее состояние

async def process_new_pack_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    if not is_english(new_name):
        await update.message.reply_text('Название должно быть на английском языке. Пожалуйста, введите название снова.')
        return AWAITING_PACK_NAME
    pack_id = context.user_data.get('selected_pack_id')
    if pack_id:
        update_pack_name(pack_id, new_name)
        await update.message.reply_text('Название стикерпака успешно обновлено.')
    else:
        await update.message.reply_text('Не удалось определить стикерпак для обновления.')
    return ConversationHandler.END

async def handle_photo_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.isdigit():
        photo_number = int(text) - 1
        image_files = context.user_data.get('image_files', [])
        if 0 <= photo_number < len(image_files):
            context.user_data['photo_to_edit'] = photo_number
            await update.message.reply_text('Отправьте новое фото для замены.')
            return EDITING_PHOTOS
        else:
            await update.message.reply_text('Некорректный номер фото.')
            return EDITING_PHOTOS
    else:
        await update.message.reply_text('Пожалуйста, введите номер фото.')
        return EDITING_PHOTOS


# Обработчик навигации и обработки
async def handle_media_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data in ['prev_media', 'next_media', 'back_to_previous_menu']:
        await handle_media_navigation_buttons(update, context, data)
    elif data == 'process_current_media':
        await process_current_media(update, context)
    else:
        await query.edit_message_text("Неизвестная команда.")

    return PROCESSING_MEDIA


async def handle_media_navigation_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    if action == 'prev_media':
        context.user_data['current_media_index'] -= 1
        if context.user_data['current_media_index'] < 0:
            context.user_data['current_media_index'] = 0
    elif action == 'next_media':
        image_files = context.user_data.get('image_files', [])
        video_files = context.user_data.get('video_files', [])
        total_media = len(image_files) + len(video_files)
        context.user_data['current_media_index'] += 1
        if context.user_data['current_media_index'] >= total_media:
            context.user_data['current_media_index'] = total_media - 1

    await show_current_media_selection_menu(update, context)


# Обработка кнопки "Обработать"
async def process_current_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    idx = context.user_data.get('current_media_index', 0)
    image_files = context.user_data.get('image_files', [])
    video_files = context.user_data.get('video_files', [])
    total_media = len(image_files) + len(video_files)

    if idx < 0 or idx >= total_media:
        await query.edit_message_text("Нет медиафайлов для обработки.")
        return PROCESSING_MEDIA

    if idx < len(image_files):
        media_type = 'image'
        media_path = image_files[idx]
        processed_variants = await process_image_variants(media_path)
    else:
        media_type = 'video'
        video_idx = idx - len(image_files)
        media_path = video_files[video_idx]
        processed_variants = await process_video_variants(media_path)

    if not processed_variants:
        await query.edit_message_text("Не удалось обработать медиафайл.")
        return PROCESSING_MEDIA

    # Отправляем три варианта как предварительный просмотр
    keyboard = [
        [InlineKeyboardButton("Вариант 1", callback_data=f'select_variant_0')],
        [InlineKeyboardButton("Вариант 2", callback_data=f'select_variant_1')],
        [InlineKeyboardButton("Вариант 3", callback_data=f'select_variant_2')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for variant_path in processed_variants:
        if media_type == 'image':
            with open(variant_path, 'rb') as img:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=img,
                    caption="Предварительный просмотр обработанного изображения"
                )
        else:
            with open(variant_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video_file,
                    caption="Предварительный просмотр обработанного видео"
                )

    await query.edit_message_text("Выберите лучший вариант:", reply_markup=reply_markup)

    # Сохраняем пути к вариантам для последующего выбора
    context.user_data['processed_variants'] = processed_variants

    return PROCESSING_MEDIA


async def handle_variant_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    match = re.match(r'select_variant_(\d+)', data)
    if not match:
        await query.edit_message_text("Некорректный выбор варианта.")
        return PROCESSING_MEDIA

    variant_index = int(match.group(1))
    processed_variants = context.user_data.get('processed_variants', [])

    if variant_index < 0 or variant_index >= len(processed_variants):
        await query.edit_message_text("Некорректный индекс варианта.")
        return PROCESSING_MEDIA

    selected_variant_path = processed_variants[variant_index]

    # Добавляем выбранный вариант в список изображений или видео
    current_index = context.user_data.get('current_media_index', 0)
    image_files = context.user_data.get('image_files', [])
    video_files = context.user_data.get('video_files', [])

    if current_index < len(image_files):
        image_files[current_index] = selected_variant_path
    else:
        video_idx = current_index - len(image_files)
        video_files[video_idx] = selected_variant_path

    context.user_data['image_files'] = image_files
    context.user_data['video_files'] = video_files

    await query.edit_message_text("Вариант выбран. Вы можете продолжить обработку или создать стикерпак.")

    # Предоставляем возможность создать стикерпак или продолжить обработку
    keyboard = [
        [
            InlineKeyboardButton("Создать стикерпак", callback_data='create_pack'),
            InlineKeyboardButton("Продолжить обработку", callback_data='continue_processing')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Что вы хотите сделать дальше?", reply_markup=reply_markup)

    return PROCESSING_MEDIA