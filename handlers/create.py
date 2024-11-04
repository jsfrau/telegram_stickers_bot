import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputSticker
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest
from PIL import Image
import traceback

import emoji
import random
from tg_stickers_bot.utils import sanitize_pack_name, log_error, log_info
from tg_stickers_bot.database import add_user_photo, add_user_video, add_sticker_pack, get_and_increment_video_counter, \
    get_and_increment_photo_counter
from tg_stickers_bot.config import BOT_USERNAME
from photo.processing.briaai import remove_background_briaai
from photo.processing.rembg import remove_background_from_image
from photo.processing.u2net import remove_background_u2net, u2net_model, save_u2net_result
from moviepy.editor import VideoFileClip

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Определяем пути для сохранения медиафайлов относительно базовой директории
USER_MEDIA_DIR = os.path.join(BASE_DIR, 'user_media')
IMAGE_BASE_DIR = os.path.join(USER_MEDIA_DIR, 'images')
VIDEO_BASE_DIR = os.path.join(USER_MEDIA_DIR, 'videos')

# Определяем состояния
from tg_stickers_bot.states import (
    AWAITING_PACK_NAME,
    PROCESSING_STICKERS,
    AWAITING_EMOJI,
    EDITING_PHOTOS,
    AWAITING_PRIVACY, PROCESSING_MEDIA, VIDEO_VALIDATION, EDITING_STICKERS, AWAITING_IMAGE_SELECTION
)

# Получение всех существующих эмодзи
all_emojis = list(emoji.EMOJI_DATA.keys())
# Дополнение списка RANDOM_EMOJIS (только одиночные эмодзи)
RANDOM_EMOJIS = [e for e in all_emojis if len(e) == 1]

async def process_image_with_briaai(image_path):
    # Вызов функции из briaai.py
    result_path = remove_background_briaai(image_path)
    return result_path

async def process_image_with_briaai_tool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Ожидайте...")
    image_path = context.user_data.get('processing_image_path')
    output_path = image_path.replace('.png', '_briaai.png')
    # Вызов функции из briaai.py
    remove_background_briaai(image_path, output_path)
    # Обновляем изображение в user_data
    idx = context.user_data.get('processing_image_index')
    context.user_data['image_files'][idx] = output_path
    # Отображаем обработанное изображение с кнопками
    with open(output_path, 'rb') as img:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=img,
            caption="Обработка завершена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Готово", callback_data='image_processing_done')],
                [InlineKeyboardButton("Отмена", callback_data='cancel_image_processing')]
            ])
        )

async def create_new_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = update.callback_query
        await query.answer()

        maximum_name_length = 64 - len('_by_') - len(BOT_USERNAME)

        hints_message = f"""Количество стикеров в паке:
- До 120 статических стикеров в одном наборе.
- До 50 анимированных стикеров в одном наборе.

Размер стикеров:
- Максимальный размер файла стикера — 512 КБ.
- Размер изображения — 512x512 пикселей.

Название стикерпака:
- Длина названия стикерпака может быть до ({maximum_name_length}) символов.
"""

        keyboard = [
            [InlineKeyboardButton("Я понял, продолжить", callback_data='continue')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(hints_message, reply_markup=reply_markup)
    except Exception as e:
        log_error(f"Ошибка в create_new_pack: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при выборе режима добавления.')

async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()

        if query.data == 'continue':
            await query.edit_message_text('Присылайте ваши стикеры.')
            context.user_data['mode'] = 'single'
            context.user_data['photo_count'] = 0
            context.user_data['video_count'] = 0
            context.user_data['document_count'] = 0
            context.user_data['image_files'] = []
            context.user_data['video_files'] = []
            return PROCESSING_STICKERS
        elif query.data == 'create_pack':
            context.user_data['emojis'] = []
            context.user_data['current_image'] = 0
            await prompt_for_emoji(update, context)
            return AWAITING_EMOJI
        elif query.data == 'edit_stickers':
            await edit_stickers(update, context)
            return EDITING_STICKERS
        elif query.data == 'process_media':
            await process_media_menu(update, context)
            return PROCESSING_MEDIA
        elif query.data == 'cancel':
            await query.edit_message_text('Создание стикерпака отменено.')
            context.user_data.clear()
            return ConversationHandler.END
        else:
            await query.edit_message_text('Неизвестная команда.')
            return ConversationHandler.END
    except Exception as e:
        log_error(f"Ошибка в handle_mode_selection: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при выборе режима.')
        return ConversationHandler.END

# Удалена функция process_zip и соответствующие обработчики

from moviepy.editor import VideoFileClip

def convert_mp4_to_webm(input_path: str, output_path: str) -> str:
    try:
        with VideoFileClip(input_path) as clip:
            # Обрезаем до 3 секунд, если длительность больше 3 секунд
            if clip.duration > 3:
                clip = clip.subclip(0, 3)

            # Вычисляем масштабный коэффициент
            max_dimension = max(clip.w, clip.h)
            if max_dimension > 512:
                scale_factor = 512 / max_dimension
                clip = clip.resize(scale_factor)
            # Если оба измерения <= 512, масштабирование не требуется

            # Устанавливаем частоту кадров до 30 FPS
            clip = clip.set_fps(30)

            # Сохраняем видео в формате WebM с кодеком VP9 и без звука
            clip.write_videofile(
                output_path,
                codec='libvpx-vp9',  # Кодек VP9
                audio=False,         # Отключаем звук
                threads=12,          # Используем несколько потоков для ускорения
                preset='medium',     # Оптимизация для качества/скорости
                bitrate='256k',      # Ограничиваем размер файла
                ffmpeg_params=['-pix_fmt', 'yuva420p']  # Устанавливаем альфа-канал
            )

        # Получаем характеристики конвертированного видео
        props = get_video_properties(output_path)
        log_info(f"Конвертация видео завершена. Характеристики: {props}")

        return output_path
    except Exception as e:
        log_error(f"Ошибка при конвертации MP4 в WebM: {str(e)}")
        raise






async def process_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_image_dir = os.path.join(IMAGE_BASE_DIR, str(user_id))
    user_video_dir = os.path.join(VIDEO_BASE_DIR, str(user_id))
    os.makedirs(user_image_dir, exist_ok=True)
    os.makedirs(user_video_dir, exist_ok=True)

    mode = context.user_data.get('mode', 'multi')  # Предполагается, что по умолчанию режим 'multi'

    if mode != 'single':
        return PROCESSING_STICKERS

    # Инициализация списков, если они ещё не инициализированы
    context.user_data.setdefault('image_files', [])
    context.user_data.setdefault('video_files', [])
    context.user_data.setdefault('photo_count', 0)
    context.user_data.setdefault('video_count', 0)

    if update.message.photo:
        # Получаем следующий уникальный счетчик для фото
        counter = get_and_increment_photo_counter(user_id)
        if counter is None:
            await update.message.reply_text('Не удалось получить счетчик фотографий.')
            return PROCESSING_STICKERS

        photo_name = f'{user_id}_{counter}.png'
        photo_path = os.path.join(user_image_dir, photo_name)

        # Обработка фото
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        temp_file_path = os.path.join(user_image_dir, f'temp_{user_id}.jpg')
        await file.download_to_drive(temp_file_path)

        img = Image.open(temp_file_path)
        img.thumbnail((512, 512))
        img.save(photo_path, 'PNG')

        # Удаляем временный файл
        os.remove(temp_file_path)

        # Добавляем информацию о фотографии в базу данных
        add_user_photo(user_id, photo_path, photo_name)

        # Обновляем данные пользователя
        context.user_data['image_files'].append(photo_path)
        context.user_data['photo_count'] += 1
        await update.message.reply_text('Фото сохранено. Нажмите кнопку ниже, чтобы обработать изображения.')
        # Обрабатываем изображение тремя методами
        #process_image_with_briaai_tool(photo_path, context.user_data['image_files'])
        process_image_with_rembg_tool(photo_path)
        process_image_with_u2net_tool(photo_path)

    elif update.message.video or (update.message.document and update.message.document.mime_type.startswith('video/')):
        # Получаем следующий уникальный счетчик для видео
        counter = get_and_increment_video_counter(user_id)
        if counter is None:
            await update.message.reply_text('Не удалось получить счетчик видео.')
            return PROCESSING_STICKERS

        video_name = f'{user_id}_{counter}.webm'
        video_path = os.path.join(user_video_dir, video_name)

        # Обработка видео
        file_id = update.message.video.file_id if update.message.video else update.message.document.file_id
        file = await context.bot.get_file(file_id)
        temp_file_path = os.path.join(user_video_dir, f'temp_{user_id}_{counter}.mp4')  # Исправлено
        await file.download_to_drive(temp_file_path)

        try:
            convert_mp4_to_webm(temp_file_path, video_path)
            # Удаляем временный файл после обработки
            os.remove(temp_file_path)
            # Добавляем информацию о видео в базу данных
            add_user_video(user_id, video_path, video_name)
            # Обновляем данные пользователя
            context.user_data['video_files'].append(video_path)
            context.user_data['video_count'] += 1
        except Exception as e:
            await update.message.reply_text('Не удалось обработать видео. Пожалуйста, попробуйте другое видео.')
            log_error(f"Ошибка при обработке видео: {str(e)}")
            return PROCESSING_STICKERS

    else:
        await update.message.reply_text('Пожалуйста, отправьте фото или видео.')
        return PROCESSING_STICKERS

    # В режиме 'single' после получения одного медиафайла показываем статус и меню
    total_count = context.user_data.get('photo_count', 0) + context.user_data.get('video_count', 0)
    photo_count = context.user_data.get('photo_count', 0)
    video_count = context.user_data.get('video_count', 0)

    keyboard = [
        [InlineKeyboardButton("Создать стикерпак", callback_data='create_pack')],
        [InlineKeyboardButton("Редактировать стикеры", callback_data='edit_stickers')],
        [InlineKeyboardButton("Обработать изображения или видео", callback_data='process_media')],  # Изменено
        [InlineKeyboardButton("Отмена", callback_data='cancel')]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    status_text = (
        f"{total_count} стикера получено. Из них {photo_count} фото и {video_count} видео. "
        f"Добавьте ещё файлы или выберите дальнейшее действие:"
    )

    # Отправляем статус и меню
    status_message = await update.message.reply_text(status_text, reply_markup=reply_markup)
    context.user_data['status_message_id'] = status_message.message_id

    return PROCESSING_STICKERS

async def handle_process_images_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    image_files = context.user_data.get('image_files', [])
    if not image_files:
        await query.edit_message_text('Нет изображений для обработки.')
        return PROCESSING_STICKERS

    for idx, image_path in enumerate(image_files):
        # Определяем пути для сохранения обработанных изображений
        briaai_path = image_path.replace('.png', '_briaai.png')
        rembg_path = image_path.replace('.png', '_rembg.png')
        u2net_path = image_path.replace('.png', '_u2net.png')

        try:
            # Обработка с помощью BriaAI
            remove_background_briaai(image_path, briaai_path)

            # Обработка с помощью RemBG
            remove_background_from_image(image_path, rembg_path)

            # Обработка с помощью U2Net
            mask = remove_background_u2net(image_path, u2net_model)
            save_u2net_result(image_path, mask, u2net_path)

        except Exception as e:
            log_error(f"Ошибка при обработке изображения {image_path}: {str(e)}", traceback.format_exc())
            await query.edit_message_text(f'Произошла ошибка при обработке изображения {os.path.basename(image_path)}.')
            return PROCESSING_STICKERS

    await query.edit_message_text('Изображения обработаны. Теперь выберите лучший вариант для каждого изображения.')
    # Начинаем процесс выбора изображений
    return await initiate_image_selection(update, context)

import re
from telegram import InputMediaPhoto

async def initiate_image_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['current_selection_index'] = 0
    context.user_data['selected_images'] = []
    return await present_image_selection(update, context)

async def present_image_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    current_index = context.user_data['current_selection_index']
    image_files = context.user_data['image_files']

    if current_index >= len(image_files):
        # Все изображения выбраны, продолжаем создание стикерпака
        await create_pack_with_selected_images(update, context)
        return ConversationHandler.END

    image_path = image_files[current_index]
    # Предполагается, что обработанные версии сохранены как:
    # image_path_briaai.png, image_path_rembg.png, image_path_u2net.png
    briaai_path = image_path.replace('.png', '_briaai.png')
    rembg_path = image_path.replace('.png', '_rembg.png')
    u2net_path = image_path.replace('.png', '_u2net.png')

    media = []
    try:
        with open(briaai_path, 'rb') as img1, open(rembg_path, 'rb') as img2, open(u2net_path, 'rb') as img3:
            media.append(InputMediaPhoto(media=img1, caption='BriaAI'))
            media.append(InputMediaPhoto(media=img2, caption='RemBG'))
            media.append(InputMediaPhoto(media=img3, caption='U2Net'))
    except Exception as e:
        log_error(f"Ошибка при открытии обработанных изображений: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Произошла ошибка при обработке изображений.')
        return ConversationHandler.END

    # Отправляем обработанные изображения как группу медиа
    await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media)

    # Отправляем кнопки для выбора лучшего варианта
    keyboard = [
        [
            InlineKeyboardButton("BriaAI", callback_data=f'select_image_{current_index}_briaai'),
            InlineKeyboardButton("RemBG", callback_data=f'select_image_{current_index}_rembg'),
            InlineKeyboardButton("U2Net", callback_data=f'select_image_{current_index}_u2net'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("Выберите лучший вариант для этого изображения:", reply_markup=reply_markup)
    return AWAITING_IMAGE_SELECTION

async def handle_image_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    match = re.match(r'select_image_(\d+)_(briaai|rembg|u2net)', data)
    if not match:
        await query.edit_message_text("Некорректный выбор.")
        return AWAITING_IMAGE_SELECTION

    index = int(match.group(1))
    tool = match.group(2)

    image_path = context.user_data['image_files'][index]
    selected_image_path = image_path.replace('.png', f'_{tool}.png')

    context.user_data['selected_images'].append(selected_image_path)
    context.user_data['current_selection_index'] = index + 1

    # Переходим к следующему изображению
    return await present_image_selection(update, context)

async def create_pack_with_selected_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    selected_images = context.user_data['selected_images']
    context.user_data['image_files'] = selected_images  # Обновляем список изображений для создания пакета
    # Очищаем временные данные
    del context.user_data['selected_images']
    del context.user_data['current_selection_index']
    # Продолжаем создание стикерпака как обычно
    await prepare_stickers_for_pack(update, context)


async def edit_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    image_files = context.user_data.get('image_files', [])
    video_files = context.user_data.get('video_files', [])
    total_files = image_files + video_files
    if not total_files:
        await update.effective_message.reply_text('Нет стикеров для редактирования.')
        return PROCESSING_STICKERS

    # Отправляем все стикеры с номерами
    for idx, sticker_path in enumerate(total_files):
        if idx < len(image_files):
            with open(sticker_path, 'rb') as img:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=img,
                    caption=f'Стикер #{idx + 1}'
                )
        else:
            with open(sticker_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video_file,
                    caption=f'Стикер #{idx + 1}'
                )

    await update.effective_message.reply_text('Какой стикер нужно изменить? Введите номер стикера.')
    return EDITING_STICKERS

async def handle_sticker_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.isdigit():
        sticker_number = int(text) - 1
        image_files = context.user_data.get('image_files', [])
        video_files = context.user_data.get('video_files', [])
        total_files = image_files + video_files
        if 0 <= sticker_number < len(total_files):
            context.user_data['sticker_to_edit'] = sticker_number
            if sticker_number < len(image_files):
                context.user_data['edit_type'] = 'image'
            else:
                context.user_data['edit_type'] = 'video'
            await update.message.reply_text('Отправьте новое фото или видео для замены.')
            return EDITING_STICKERS
        else:
            await update.message.reply_text('Некорректный номер стикера.')
            return EDITING_STICKERS
    else:
        await update.message.reply_text('Пожалуйста, введите номер стикера.')
        return EDITING_STICKERS

async def handle_new_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        sticker_number = context.user_data.get('sticker_to_edit')
        edit_type = context.user_data.get('edit_type')
        if sticker_number is None or edit_type is None:
            await update.message.reply_text('Не выбран номер стикера для замены.')
            return EDITING_STICKERS

        if update.message.photo and edit_type == 'image':
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            file_path = f'images/sticker_{sticker_number}.jpg'
            await file.download_to_drive(file_path)

            img = Image.open(file_path)
            img.thumbnail((512, 512), Image.ANTIALIAS)
            processed_path = f'processed/sticker_{sticker_number}.png'
            img.save(processed_path, 'PNG')

            context.user_data['image_files'][sticker_number] = processed_path
            await update.message.reply_text('Фото заменено. Все готово? Выберите: Изменить ещё или Готово.', reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Изменить ещё", callback_data='edit_more'),
                    InlineKeyboardButton("Готово", callback_data='edit_done')
                ]
            ]))
            return EDITING_STICKERS

        elif (update.message.video or update.message.document) and edit_type == 'video':
            video_idx = sticker_number - len(context.user_data['image_files'])
            file = await context.bot.get_file(update.message.video.file_id if update.message.video else update.message.document.file_id)
            file_extension = '.mp4' if update.message.video else os.path.splitext(update.message.document.file_name)[1]
            file_path = f'videos/sticker_{video_idx}{file_extension}'
            await file.download_to_drive(file_path)

            # Обрабатываем видео
            converted_path = f'videos/sticker_{video_idx}.webm'
            process_video(file_path, converted_path)

            context.user_data['video_files'][video_idx] = converted_path

            await update.message.reply_text('Видео заменено. Все готово? Выберите: Изменить ещё или Готово.', reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Изменить ещё", callback_data='edit_more'),
                    InlineKeyboardButton("Готово", callback_data='edit_done')
                ]
            ]))
            return EDITING_STICKERS

        else:
            await update.message.reply_text('Пожалуйста, отправьте фото или видео соответствующего типа.')
            return EDITING_STICKERS
    except Exception as e:
        log_error(f"Ошибка в handle_new_sticker: {str(e)}", traceback.format_exc())
        await update.message.reply_text('Произошла ошибка при замене стикера.')
        return EDITING_STICKERS


# Дополнительная функция для конвертации видео в webm
def process_video(input_path, output_path):
    try:
        # Загружаем видео
        clip = VideoFileClip(input_path)

        # Обрезаем до 3 секунд
        if clip.duration > 3:
            clip = clip.subclip(0, 3)

        # Вычисляем масштабный коэффициент
        max_dimension = max(clip.w, clip.h)
        if max_dimension > 512:
            scale_factor = 512 / max_dimension
            clip = clip.resize(scale_factor)
        # Если оба измерения <= 512, масштабирование не требуется

        # Сохраняем видео в формате WebM с нужными параметрами, убирая аудиокодек
        clip.write_videofile(
            output_path,
            codec="libvpx-vp9",      # Кодек VP9 для видео
            bitrate="256k",          # Битрейт
            ffmpeg_params=["-crf", "30", "-pix_fmt", "yuva420p"]  # Дополнительные параметры
        )

    except Exception as e:
        # Логируем ошибку, если что-то пошло не так
        log_error(f"Ошибка при конвертации видео: {str(e)}", traceback.format_exc())
        raise  # Повторно выбрасываем исключение для обработки



# handlers/create.py

# handlers/create.py

def is_valid_video(video_path: str) -> (bool, str):
    try:
        # Проверка размера файла
        max_size = 512 * 1024  # 512 KB
        file_size = os.path.getsize(video_path)
        if file_size > max_size:
            return False, f"Размер файла {file_size} байт превышает максимальный 512 КБ."

        # Открытие видео с помощью moviepy
        with VideoFileClip(video_path) as clip:
            # Проверка длительности
            duration = clip.duration
            if duration > 3.0:
                return False, f"Длительность видео {duration} секунд превышает максимально допустимые 3 секунды."

            # Проверка размеров видео
            width, height = clip.size
            if width > 512 or height > 512:
                return False, f"Разрешение видео {width}x{height} пикселей превышает максимально допустимые 512x512."

        return True, ""
    except Exception as e:
        log_error(f"Ошибка при проверке видео: {str(e)}")
        return False, f"Ошибка при проверке видео: {str(e)}"

from moviepy.editor import ImageClip, VideoFileClip

def resize_clip(clip: VideoFileClip) -> VideoFileClip:
    """
    Масштабирует видео или изображение, чтобы ни ширина, ни высота не превышали 512 пикселей,
    сохраняя соотношение сторон.
    """
    max_dimension = max(clip.w, clip.h)
    if max_dimension > 512:
        scale_factor = 512 / max_dimension
        return resize_clip(clip)
    return clip

from moviepy.editor import ImageClip

def convert_image_to_webm(input_image_path: str, output_video_path: str) -> str:
    try:
        # Загружаем изображение как ImageClip
        clip = ImageClip(input_image_path)

        # Устанавливаем длительность видео (3 секунды)
        clip = clip.set_duration(3)

        # Масштабируем изображение так, чтобы ни ширина, ни высота не превышали 512 пикселей
        clip = resize_clip(clip)

        # Устанавливаем частоту кадров до 30 FPS
        clip = clip.set_fps(30)

        # Сохраняем видео в формате WebM с кодеком VP9 и без звука
        clip.write_videofile(
            output_video_path,
            codec='libvpx-vp9',        # Кодек VP9
            audio=False,               # Отключаем звук
            threads=12,                # Используем несколько потоков для ускорения
            preset='medium',           # Оптимизация для качества/скорости
            ffmpeg_params=['-pix_fmt', 'yuva420p']  # Устанавливаем альфа-канал
        )

        # Получаем характеристики конвертированного видео
        props = get_video_properties(output_video_path)
        log_info(f"Конвертация изображения в видео завершена. Характеристики: {props}")

        return output_video_path
    except Exception as e:
        log_error(f"Ошибка при конвертации изображения в WebM: {str(e)}")
        raise




# handlers/create.py

async def prepare_stickers_for_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Проверка валидности видео
    invalid_videos = []
    for video_path in context.user_data.get('video_files', []):
        is_valid, reason = is_valid_video(video_path)
        if not is_valid:
            invalid_videos.append((video_path, reason))

    if invalid_videos:
        context.user_data['invalid_videos'] = invalid_videos
        # Создаём детализированное сообщение с причинами
        messages = [f"{os.path.basename(path)}: {reason}" for path, reason in invalid_videos]
        message_text = f"{len(invalid_videos)} файлов не соответствуют условиям:\n" + "\n".join(messages)
        await update.effective_message.reply_text(message_text)
        await show_video_validation_menu(update, context)
        return

    # Обработка изображений и преобразование в видео, если нужны видеостикеры
    image_files = context.user_data.get('image_files', [])
    video_files = context.user_data.get('video_files', [])
    emojis = context.user_data.get('emojis', [])

    if video_files and image_files:  # Если есть и изображения, и видео, конвертируем изображения
        for idx, image_path in enumerate(image_files):
            output_path = image_path.replace('.png', '_converted.webm')
            try:
                convert_image_to_webm(image_path, output_path)
                video_files.append(output_path)
                # Логируем характеристики конвертированного видео
                props = get_video_properties(output_path)
                log_info(f"Конвертация изображения в видео завершена. Характеристики: {props}")
            except Exception as e:
                log_error(f"Не удалось конвертировать изображение {image_path} в WebM: {str(e)}")
                continue

        # Удаляем обработанные изображения, так как они заменены видеофайлами
        image_files.clear()

    # Создание стикерпаков для изображений
    if image_files:
        await create_sticker_pack(update, context, image_files, emojis[:len(image_files)], 'static')

    # Создание стикерпаков для видео
    if video_files:
        await create_sticker_pack(update, context, video_files, emojis[len(image_files):], 'video')

    # Очищаем данные пользователя
    context.user_data.clear()

# handlers/create.py

def get_video_properties(video_path: str) -> dict:
    try:
        with VideoFileClip(video_path) as clip:
            return {
                'duration': clip.duration,
                'width': clip.w,
                'height': clip.h,
                'fps': clip.fps,
                'file_size': os.path.getsize(video_path)
            }
    except Exception as e:
        log_error(f"Ошибка при получении характеристик видео: {str(e)}")
        return {}



async def show_video_validation_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['current_invalid_video'] = 0
    await show_current_invalid_video(update, context)
    return VIDEO_VALIDATION

# handlers/create.py

async def show_current_invalid_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = context.user_data.get('current_invalid_video', 0)
    invalid_videos = context.user_data.get('invalid_videos', [])
    if idx < 0 or idx >= len(invalid_videos):
        await update.effective_message.reply_text("Нет больше видео для отображения.")
        return

    video_path, reason = invalid_videos[idx]
    video_filename = os.path.basename(video_path)
    total_videos = len(invalid_videos)

    with open(video_path, 'rb') as video_file:
        await context.bot.send_video(
            chat_id=update.effective_chat.id,
            video=video_file,
            caption=f"Видео {idx + 1} из {total_videos}: {video_filename}\nПричина: {reason}"
        )

    keyboard = [
        [
            InlineKeyboardButton("⬅️", callback_data='prev_invalid_video'),
            InlineKeyboardButton("➡️", callback_data='next_invalid_video')
        ],
        [
            InlineKeyboardButton("✂️", callback_data='trim_current_video'),
            InlineKeyboardButton("✂️✂️", callback_data='trim_all_videos')
        ],
        [
            InlineKeyboardButton("🗑️", callback_data='delete_current_video'),
            InlineKeyboardButton("🔙", callback_data='back_to_previous_menu')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("Выберите действие:", reply_markup=reply_markup)

# handlers/create.py

async def handle_video_validation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    log_info(f"Обработка действия: {data}")
    if data == 'trim_current_video':
        await trim_current_video(update, context)
    elif data == 'trim_all_videos':
        await trim_all_videos(update, context)
    elif data == 'delete_current_video':
        await delete_current_video(update, context)
    elif data == 'prev_invalid_video':
        await show_prev_invalid_video(update, context)
    elif data == 'next_invalid_video':
        await show_next_invalid_video(update, context)
    elif data == 'back_to_previous_menu':
        # Возвращаемся к предыдущему меню
        await prepare_stickers_for_pack(update, context)
        return ConversationHandler.END
    return VIDEO_VALIDATION


async def show_video_validation_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['current_invalid_video'] = 0
    await show_current_invalid_video(update, context)
    return VIDEO_VALIDATION

async def handle_video_validation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == 'trim_current_video':
        await trim_current_video(update, context)
    elif data == 'trim_all_videos':
        await trim_all_videos(update, context)
    elif data == 'delete_current_video':
        await delete_current_video(update, context)
    elif data == 'prev_invalid_video':
        await show_prev_invalid_video(update, context)
    elif data == 'next_invalid_video':
        await show_next_invalid_video(update, context)
    elif data == 'back_to_previous_menu':
        # Возвращаемся к предыдущему меню
        await prepare_stickers_for_pack(update, context)
        return ConversationHandler.END
    return VIDEO_VALIDATION

async def trim_current_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = context.user_data.get('current_invalid_video', 0)
    invalid_videos = context.user_data.get('invalid_videos', [])
    if idx < 0 or idx >= len(invalid_videos):
        await update.effective_message.reply_text("Нет видео для обрезки.")
        return

    video_path = invalid_videos[idx]
    await update.effective_message.reply_text("Обрезка видео, ожидайте...")
    new_video_path = await trim_video(video_path)

    # Заменяем видео в списках
    context.user_data['video_files'].append(new_video_path)
    invalid_videos.pop(idx)

    if not invalid_videos:
        # Если больше нет невалидных видео, продолжаем
        await update.effective_message.reply_text("Все видео обработаны.")
        await prepare_stickers_for_pack(update, context)
        return

    else:
        # Показываем следующее невалидное видео
        if idx >= len(invalid_videos):
            context.user_data['current_invalid_video'] = len(invalid_videos) - 1
        await show_current_invalid_video(update, context)

async def trim_all_videos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    invalid_videos = context.user_data.get('invalid_videos', [])
    await update.effective_message.reply_text("Обрезка всех видео, ожидайте...")
    for video_path in invalid_videos:
        new_video_path = await trim_video(video_path)
        context.user_data['video_files'].append(new_video_path)
    # Очищаем список невалидных видео
    context.user_data['invalid_videos'] = []
    await update.effective_message.reply_text("Все видео обработаны.")
    await prepare_stickers_for_pack(update, context)

async def delete_current_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = context.user_data.get('current_invalid_video', 0)
    invalid_videos = context.user_data.get('invalid_videos', [])
    if idx < 0 or idx >= len(invalid_videos):
        await update.effective_message.reply_text("Нет видео для удаления.")
        return

    video_path = invalid_videos.pop(idx)
    # Не удаляем физически файл, но удаляем из списков
    await update.effective_message.reply_text("Видео удалено из списка.")
    if not invalid_videos:
        await update.effective_message.reply_text("Все видео обработаны.")
        await prepare_stickers_for_pack(update, context)
        return
    else:
        if idx >= len(invalid_videos):
            context.user_data['current_invalid_video'] = len(invalid_videos) - 1
        await show_current_invalid_video(update, context)

async def show_prev_invalid_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['current_invalid_video'] -= 1
    if context.user_data['current_invalid_video'] < 0:
        context.user_data['current_invalid_video'] = 0
    await show_current_invalid_video(update, context)

async def show_next_invalid_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['current_invalid_video'] += 1
    invalid_videos = context.user_data.get('invalid_videos', [])
    if context.user_data['current_invalid_video'] >= len(invalid_videos):
        context.user_data['current_invalid_video'] = len(invalid_videos) - 1
    await show_current_invalid_video(update, context)

from ffmpeg import _ffmpeg
async def trim_video(video_path: str) -> str:
    try:
        output_path = video_path.replace('.mp4', '_trimmed.mp4')
        (
            _ffmpeg
            .input(video_path)
            .output(output_path, ss=0, t=3, c='copy')  # Обрезаем первые 5 секунд
            .run(overwrite_output=True)
        )
        return output_path
    except Exception as e:
        log_error(f"Ошибка при обрезке видео: {str(e)}")
        return video_path  # Возвращаем оригинальное видео, если обрезка не удалась

async def process_media_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['current_media_index'] = 0
    await show_current_media_selection_menu(update, context)
    return PROCESSING_MEDIA

async def show_current_media_selection_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = context.user_data.get('current_media_index', 0)
    image_files = context.user_data.get('image_files', [])
    video_files = context.user_data.get('video_files', [])
    total_media = len(image_files) + len(video_files)

    if idx < 0 or idx >= total_media:
        await update.effective_message.reply_text("Нет медиафайлов для отображения.")
        return

    if idx < len(image_files):
        media_type = 'image'
        media_path = image_files[idx]
        with open(media_path, 'rb') as img:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img,
                caption=f"Изображение {idx + 1} из {total_media}"
            )
    else:
        media_type = 'video'
        video_idx = idx - len(image_files)
        media_path = video_files[video_idx]
        with open(media_path, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_file,
                caption=f"Видео {video_idx + 1} из {total_media}"
            )

    keyboard = [
        [
            InlineKeyboardButton("⬅️", callback_data='prev_media'),
            InlineKeyboardButton("➡️", callback_data='next_media')
        ],
        [
            InlineKeyboardButton("Обработать", callback_data='process_current_media'),
            InlineKeyboardButton("Назад", callback_data='back_to_previous_menu')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("Выберите действие:", reply_markup=reply_markup)


async def handle_media_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == 'prev_media':
        context.user_data['current_media_index'] -= 1
        if context.user_data['current_media_index'] < 0:
            context.user_data['current_media_index'] = 0
        await show_current_media_selection_menu(update, context)
    elif data == 'next_media':
        context.user_data['current_media_index'] += 1
        image_files = context.user_data.get('image_files', [])
        video_files = context.user_data.get('video_files', [])
        total_media = len(image_files) + len(video_files)
        if context.user_data['current_media_index'] >= total_media:
            context.user_data['current_media_index'] = total_media - 1
        await show_current_media_selection_menu(update, context)
    elif data == 'back_to_previous_menu':
        await query.edit_message_text("Возвращаемся к предыдущему меню.")
        # Здесь вызываем нужную функцию для возврата к предыдущему состоянию
        return PROCESSING_STICKERS
    elif data == 'process_current_media':
        await process_current_media(update, context)
    else:
        await query.edit_message_text("Неизвестная команда.")

    return PROCESSING_MEDIA

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

async def process_image_variants(image_path: str) -> list:
    try:
        # Создаём три варианта изображения с разными обработками
        briaai_path = image_path.replace('.png', '_briaai.png')
        rembg_path = image_path.replace('.png', '_rembg.png')
        u2net_path = image_path.replace('.png', '_u2net.png')

        # Обработка с помощью BriaAI
        remove_background_briaai(image_path, briaai_path)

        # Обработка с помощью RemBG
        remove_background_from_image(image_path, rembg_path)

        # Обработка с помощью U2Net
        mask = remove_background_u2net(image_path, u2net_model)
        save_u2net_result(image_path, mask, u2net_path)

        return [briaai_path, rembg_path, u2net_path]
    except Exception as e:
        log_error(f"Ошибка при обработке изображения {image_path}: {str(e)}", traceback.format_exc())
        return []

async def process_video_variants(video_path: str) -> list:
    try:
        # Создаём три варианта видео с разными обработками
        variant1 = video_path.replace('.webm', '_variant1.webm')
        variant2 = video_path.replace('.webm', '_variant2.webm')
        variant3 = video_path.replace('.webm', '_variant3.webm')

        # Пример обработки: обрезка, изменение размера и т.д.
        # Здесь вы можете вызвать свои функции обработки видео
        # Для простоты приведу пример обрезки видео до 3 секунд
        await convert_mp4_to_webm(video_path, variant1)  # Уже существует
        # Создайте другие варианты по необходимости
        # variant2, variant3

        return [variant1]  # Добавьте остальные варианты после создания
    except Exception as e:
        log_error(f"Ошибка при обработке видео {video_path}: {str(e)}", traceback.format_exc())
        return []

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



async def show_current_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = context.user_data.get('current_media_index', 0)
    image_files = context.user_data.get('image_files', [])
    video_files = context.user_data.get('video_files', [])
    total_media = len(image_files) + len(video_files)

    if idx < 0 or idx >= total_media:
        await update.effective_message.reply_text("Нет больше медиафайлов для обработки.")
        return

    if idx < len(image_files):
        media_type = 'image'
        media_path = image_files[idx]
        with open(media_path, 'rb') as img:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img,
                caption=f"Изображение {idx + 1} из {total_media}"
            )
    else:
        media_type = 'video'
        video_idx = idx - len(image_files)
        media_path = video_files[video_idx]
        with open(media_path, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_file,
                caption=f"Видео {video_idx + 1} из {total_media}"
            )

    context.user_data['current_media_type'] = media_type
    context.user_data['current_media_path'] = media_path

    keyboard = []
    if media_type == 'image':
        keyboard.append([
            InlineKeyboardButton("⬅️", callback_data='prev_media'),
            InlineKeyboardButton("➡️", callback_data='next_media')
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("Вырезать объект на видео", callback_data='process_video'),
            InlineKeyboardButton("Обрезать первые 5 секунд видео", callback_data='trim_video')
        ])
    keyboard.append([
        InlineKeyboardButton("Назад", callback_data='back_to_previous_menu'),
        InlineKeyboardButton("Отмена", callback_data='cancel_processing')
    ])
    keyboard.append([
        InlineKeyboardButton("Назад", callback_data='prev_media'),
        InlineKeyboardButton("Далее", callback_data='next_media')
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("Выберите действие:", reply_markup=reply_markup)

def resize_video(clip: VideoFileClip) -> VideoFileClip:
    max_dimension = max(clip.w, clip.h)
    if max_dimension > 512:
        scale_factor = 512 / max_dimension
        return clip.resize(scale_factor)
    return clip


async def process_current_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Ожидайте...")
    video_path = context.user_data.get('current_media_path')
    output_path = video_path.replace('.webm', '_processed.webm')

    try:
        # Обработка видео с корректным масштабированием
        with VideoFileClip(video_path) as clip:
            # Обрезаем до 3 секунд, если необходимо
            if clip.duration > 3:
                clip = clip.subclip(0, 3)

            # Вычисляем масштабный коэффициент
            max_dimension = max(clip.w, clip.h)
            if max_dimension > 512:
                scale_factor = 512 / max_dimension
                clip = clip.resize(scale_factor)

            # Сохраняем обработанное видео
            clip.write_videofile(
                output_path,
                codec="libvpx-vp9",
                bitrate="256k",
                ffmpeg_params=["-crf", "30", "-pix_fmt", "yuva420p"]
            )

        # Обновляем видео в user_data
        idx = context.user_data.get('current_media_index') - len(context.user_data.get('image_files', []))
        context.user_data['video_files'][idx] = output_path

        # Отображаем обработанное видео с кнопками
        with open(output_path, 'rb') as vid:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=vid,
                caption="Обработка завершена.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Готово", callback_data='video_processing_done')],
                    [InlineKeyboardButton("Отмена", callback_data='cancel_video_processing')]
                ])
            )
    except Exception as e:
        await update.message.reply_text('Не удалось обработать видео. Пожалуйста, попробуйте другое видео.')
        log_error(f"Ошибка при обработке видео: {str(e)}")
        return PROCESSING_STICKERS



async def handle_media_processing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == 'process_image':
        await process_current_image(update, context)
    elif data == 'process_all_images':
        await process_all_images(update, context)
    elif data == 'process_video':
        await process_current_video(update, context)
    elif data == 'trim_video':
        await trim_current_video(update, context)
    elif data == 'prev_media':
        context.user_data['current_media_index'] -= 1
        if context.user_data['current_media_index'] < 0:
            context.user_data['current_media_index'] = 0
        await show_current_media(update, context)
    elif data == 'next_media':
        context.user_data['current_media_index'] += 1
        total_media = len(context.user_data.get('image_files', [])) + len(context.user_data.get('video_files', []))
        if context.user_data['current_media_index'] >= total_media:
            context.user_data['current_media_index'] = total_media - 1
        await show_current_media(update, context)
    elif data == 'back_to_previous_menu':
        await prepare_stickers_for_pack(update, context)
        return ConversationHandler.END
    elif data == 'process_with_briaai':
        await process_image_with_briaai(update, context)
    elif data == 'process_with_rembg':
        await process_image_with_rembg(update, context)
    elif data == 'process_with_u2net':
        await process_image_with_u2net(update, context)
    elif data == 'image_processing_done':
        await update.effective_message.reply_text("Изображение обновлено.")
        await show_current_media(update, context)
        return PROCESSING_MEDIA
    elif data == 'cancel_image_processing':
        await update.effective_message.reply_text("Изменения отменены.")
        await show_current_media(update, context)
    elif data == 'video_processing_done':
        await update.effective_message.reply_text("Видео обновлено.")
        await show_current_media(update, context)
        return PROCESSING_MEDIA
    elif data == 'cancel_video_processing':
        await update.effective_message.reply_text("Изменения отменены.")
        await show_current_media(update, context)
    elif data == 'cancel_all_images_processing':
        await cancel_all_images_processing(update, context)
        return PROCESSING_MEDIA


async def process_all_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Обрезка всех изображений, ожидайте...")
    image_files = context.user_data.get('image_files', [])
    processed_files = []
    for idx, image_path in enumerate(image_files):
        output_path = image_path.replace('.png', '_processed.png')
        # Выберите одну из технологий обработки или примените по очереди
        remove_background_briaai(image_path, output_path)
        processed_files.append(output_path)
    # Сохраняем оригинальные изображения на случай отмены
    context.user_data['original_image_files'] = image_files.copy()
    # Обновляем изображения в user_data
    context.user_data['image_files'] = processed_files
    await update.effective_message.reply_text("Все изображения обработаны.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Отмена", callback_data='cancel_all_images_processing')]
    ]))

async def cancel_all_images_processing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Восстанавливаем оригинальные изображения
    context.user_data['image_files'] = context.user_data['original_image_files']
    del context.user_data['original_image_files']
    await update.effective_message.reply_text("Изменения отменены.")
    await show_current_media(update, context)

def process_image_with_rembg_tool(image_path):
    rembg_path = image_path.replace('.png', '_rembg.png')
    remove_background_from_image(image_path)
    return rembg_path

def process_image_with_u2net_tool(image_path):
    u2net_path = image_path.replace('.png', '_u2net.png')
    mask = remove_background_u2net(image_path, u2net_model)
    save_u2net_result(image_path, mask, u2net_path)
    return u2net_path

# Пример функции обработки изображения с помощью RemBG
async def process_current_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Выберите технологию обрезки:", reply_markup=InlineKeyboardMarkup([
        [
            InlineKeyboardButton("BriaAI", callback_data='process_with_briaai'),
            InlineKeyboardButton("RemBG", callback_data='process_with_rembg'),
            InlineKeyboardButton("U2Net", callback_data='process_with_u2net')
        ],
        [
            InlineKeyboardButton("Отмена", callback_data='cancel_image_processing')
        ]
    ]))
    # Сохраняем состояние
    context.user_data['processing_image_path'] = context.user_data.get('current_media_path')
    context.user_data['processing_image_index'] = context.user_data.get('current_media_index')

async def process_image_with_briaai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Ожидайте...")

    image_path = context.user_data.get('processing_image_path')
    output_path = image_path.replace('.png', '_briaai.png')
    remove_background_briaai(image_path, output_path)

    # Обновляем изображение в user_data
    idx = context.user_data.get('processing_image_index')
    context.user_data['image_files'][idx] = output_path

    await update.effective_message.reply_text("Обработка завершена.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Готово", callback_data='image_processing_done')],
        [InlineKeyboardButton("Отмена", callback_data='cancel_image_processing')]
    ]))

async def show_current_invalid_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = context.user_data['current_invalid_video']
    video_path = context.user_data['invalid_videos'][idx]
    with open(video_path, 'rb') as video_file:
        await context.bot.send_video(
            chat_id=update.effective_chat.id,
            video=video_file,
            caption=f"Видео {idx + 1} из {len(context.user_data['invalid_videos'])}"
        )

    keyboard = [
        [
            InlineKeyboardButton("Обрезать видео по 5 секунд в начале", callback_data='trim_current_video'),
            InlineKeyboardButton("Обрезать все видео", callback_data='trim_all_videos')
        ],
        [
            InlineKeyboardButton("Удалить", callback_data='delete_current_video'),
            InlineKeyboardButton("Назад", callback_data='back_to_previous_menu')
        ],
        [
            InlineKeyboardButton("⬅️", callback_data='prev_invalid_video'),
            InlineKeyboardButton("➡️", callback_data='next_invalid_video')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("Выберите действие:", reply_markup=reply_markup)

async def handle_pack_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_text = update.message.text
    if not is_english(message_text):
        await update.message.reply_text('Название должно быть на английском языке. Пожалуйста, введите название снова.')
        return AWAITING_PACK_NAME
    context.user_data['pack_name'] = message_text
    # Устанавливаем имя автора как username пользователя
    user = update.effective_user
    context.user_data['author_name'] = user.username or user.full_name
    # Спрашиваем о приватности
    keyboard = [
        [InlineKeyboardButton("Приватный", callback_data='private')],
        [InlineKeyboardButton("Публичный", callback_data='public')],
        [InlineKeyboardButton("Назад", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Сделать стикерпак приватным или общедоступным?', reply_markup=reply_markup)
    return AWAITING_PRIVACY

async def handle_privacy_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'private':
        context.user_data['is_private'] = True
    elif query.data == 'public':
        context.user_data['is_private'] = False
    elif query.data == 'back_to_main':
        await ask_for_pack_name(update, context)
        return AWAITING_PACK_NAME
    else:
        await query.edit_message_text('Неверный выбор. Пожалуйста, выберите приватность стикерпака.')
        return AWAITING_PRIVACY
    await query.edit_message_text('Спасибо! Ваш стикерпак создается.')
    # Продолжаем создание стикерпака
    await prepare_stickers_for_pack(update, context)
    return ConversationHandler.END

async def create_sticker_pack(update, context, sticker_files, emojis, sticker_format):
    user_id = update.effective_user.id
    pack_name_base = context.user_data.get('pack_name')
    pack_name = sanitize_pack_name(f"{pack_name_base}_{sticker_format}", BOT_USERNAME)
    author_name = context.user_data.get('author_name')
    is_private = context.user_data.get('is_private', True)

    # Дополняем список эмодзи, если их меньше, чем стикеров
    while len(emojis) < len(sticker_files):
        emojis.append(random.choice(RANDOM_EMOJIS))

    try:
        # Создаем новый стикерпак с первым стикером
        first_sticker_path = sticker_files[0]
        first_emoji = emojis[0]
        with open(first_sticker_path, 'rb') as sticker_file:
            if sticker_format == 'video':
                first_sticker = InputSticker(
                    sticker=sticker_file,
                    emoji_list=[first_emoji],
                    mask_position=None,
                    keywords=None,
                    format='video'  # Указываем формат для видео
                )
            else:
                first_sticker = InputSticker(
                    sticker=sticker_file,
                    emoji_list=[first_emoji],
                    mask_position=None,
                    keywords=None,
                    format = 'static'
                )
            await context.bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=pack_name_base,
                stickers=[first_sticker]
            )
    except Exception as e:
        log_error(f"Ошибка при создании нового стикерпака: {str(e)}", traceback.format_exc())
        await update.effective_message.reply_text('Не удалось создать новый стикерпак.')
        return

    # Добавляем остальные стикеры
    for idx in range(1, len(sticker_files)):
        sticker_path = sticker_files[idx]
        emoji_assigned = emojis[idx]
        with open(sticker_path, 'rb') as sticker_file:
            try:
                if sticker_format == 'video':
                    sticker = InputSticker(
                        sticker=sticker_file,
                        emoji_list=[emoji_assigned],
                        mask_position=None,
                        keywords=None,
                        format='video'
                    )
                else:
                    sticker = InputSticker(
                        sticker=sticker_file,
                        emoji_list=[emoji_assigned],
                        mask_position=None,
                        keywords=None,
                        format='static'
                    )
                await context.bot.add_sticker_to_set(
                    user_id=user_id,
                    name=pack_name,
                    sticker=sticker
                )
                await asyncio.sleep(0.5)  # Избегаем перегрузки запросами
            except Exception as e:
                log_error(f"Ошибка при добавлении стикера: {str(e)}", traceback.format_exc())
                await update.effective_message.reply_text(f'Не удалось добавить стикер {idx + 1}.')
                continue

    # Отправляем сообщение об успешном создании
    pack_link = f'https://t.me/addstickers/{pack_name}'
    await update.effective_message.reply_text(
        f'Стикерпак "{pack_name_base}" успешно создан!\nСсылка: {pack_link}'
    )

    # Сохраняем стикерпак в базе данных
    add_sticker_pack(user_id, pack_name_base, author_name, pack_link, is_private)



async def process_image_with_rembg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Ожидайте...")

    image_path = context.user_data.get('processing_image_path')
    output_path = image_path.replace('.png', '_rembg.png')

    # Вызов функции из rembg.py
    result_image = remove_background_from_image(image_path)
    result_image.save(output_path)

    # Обновляем изображение в user_data
    idx = context.user_data.get('processing_image_index')
    context.user_data['image_files'][idx] = output_path

    # Отображаем обработанное изображение с кнопками
    with open(output_path, 'rb') as img:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=img,
            caption="Обработка завершена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Готово", callback_data='image_processing_done')],
                [InlineKeyboardButton("Отмена", callback_data='cancel_image_processing')]
            ])
        )

async def process_image_with_u2net(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Ожидайте...")

    image_path = context.user_data.get('processing_image_path')
    output_path = image_path.replace('.png', '_u2net.png')

    # Вызов функций из u2net.py
    mask = remove_background_u2net(image_path, u2net_model)
    save_u2net_result(image_path, mask, output_path)

    # Обновляем изображение в user_data
    idx = context.user_data.get('processing_image_index')
    context.user_data['image_files'][idx] = output_path

    # Отображаем обработанное изображение с кнопками
    with open(output_path, 'rb') as img:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=img,
            caption="Обработка завершена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Готово", callback_data='image_processing_done')],
                [InlineKeyboardButton("Отмена", callback_data='cancel_image_processing')]
            ])
        )



async def prompt_for_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    current = context.user_data.get('current_sticker_index', 0)
    image_files = context.user_data.get('image_files', [])
    video_files = context.user_data.get('video_files', [])
    sticker_files = image_files + video_files

    if current < len(sticker_files):
        sticker_path = sticker_files[current]
        if current < len(image_files):
            # Обработка изображения
            with open(sticker_path, 'rb') as img:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=img,
                    caption=f'Пришлите эмодзи для этого стикера {current + 1}/{len(sticker_files)}:',
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("Пропустить", callback_data='skip'),
                            InlineKeyboardButton("Пропустить все", callback_data='skip_all')
                        ]
                    ])
                )
        else:
            # Обработка видео
            with open(sticker_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video_file,
                    caption=f'Пришлите эмодзи для этого стикера {current + 1}/{len(sticker_files)}:',
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("Пропустить", callback_data='skip'),
                            InlineKeyboardButton("Пропустить все", callback_data='skip_all')
                        ]
                    ])
                )
        return AWAITING_EMOJI
    else:
        await ask_for_pack_name(update, context)
        return AWAITING_PACK_NAME


async def handle_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    emoji_input = update.message.text.strip()

    if not is_valid_emoji(emoji_input):
        await update.message.reply_text('Пожалуйста, отправьте допустимый эмодзи или нажмите "Пропустить".')
        return AWAITING_EMOJI

    context.user_data['emojis'].append(emoji_input)
    context.user_data['current_sticker_index'] += 1

    return await prompt_for_emoji(update, context)


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not RANDOM_EMOJIS:
        await update.callback_query.answer(text="Нет доступных эмодзи для назначения.", show_alert=True)
        return AWAITING_EMOJI

    random_emoji = random.choice(RANDOM_EMOJIS)
    context.user_data['emojis'].append(random_emoji)
    context.user_data['current_sticker_index'] += 1

    await update.callback_query.answer()
    return await prompt_for_emoji(update, context)


async def handle_skip_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    image_files = context.user_data.get('image_files', [])
    current = context.user_data.get('current_image', 0)

    while current < len(image_files):
        random_emoji = random.choice(RANDOM_EMOJIS)
        context.user_data['emojis'].append(random_emoji)
        current += 1

    context.user_data['current_image'] = current
    await update.callback_query.answer()
    await ask_for_pack_name(update, context)
    return AWAITING_PACK_NAME

def is_valid_emoji(s: str) -> bool:
    return s in emoji.EMOJI_DATA

async def ask_for_pack_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text('Введите название для стикерпака (только английские буквы и цифры):')
    return AWAITING_PACK_NAME

def is_english(text: str) -> bool:
    return all(ord(c) < 128 for c in text)

# Функции редактирования фотографий:

async def edit_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    image_files = context.user_data.get('image_files', [])
    if not image_files:
        await update.effective_message.reply_text('Нет фотографий для редактирования.')
        return PROCESSING_STICKERS

    # Отправляем все фото с номерами
    for idx, image_path in enumerate(image_files):
        with open(image_path, 'rb') as img:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img,
                caption=f'Фото #{idx + 1}'
            )

    await update.effective_message.reply_text('Какое фото нужно изменить? Введите номер фото.')
    return EDITING_PHOTOS



async def handle_new_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        photo_number = context.user_data.get('photo_to_edit')
        if photo_number is None:
            await update.message.reply_text('Не выбран номер фото для замены.')
            return EDITING_PHOTOS

        file = await context.bot.get_file(update.message.photo[-1].file_id)
        file_path = f'images/photo_{photo_number}.jpg'
        await file.download_to_drive(file_path)

        img = Image.open(file_path)
        # Изменено: Масштабирование без жесткого подгонки до 512x512
        img.thumbnail((512, 512), Image.ANTIALIAS)
        processed_path = f'processed/sticker_{photo_number}.png'
        img.save(processed_path, 'PNG')

        context.user_data['image_files'][photo_number] = processed_path
        await update.message.reply_text('Фото заменено. Все готово? Выберите: Изменить ещё или Готово.', reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Изменить ещё", callback_data='edit_more'),
                InlineKeyboardButton("Готово", callback_data='edit_done')
            ]
        ]))
        return EDITING_PHOTOS
    except Exception as e:
        log_error(f"Ошибка в handle_new_photo: {str(e)}", traceback.format_exc())
        await update.message.reply_text('Произошла ошибка при замене фотографии.')
        return EDITING_PHOTOS

async def handle_edit_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == 'edit_more':
        await edit_photos(update, context)
        return EDITING_PHOTOS
    elif query.data == 'edit_done':
        context.user_data['current_image'] = 0
        await prompt_for_emoji(update, context)
        return AWAITING_EMOJI
    else:
        await query.edit_message_text('Неизвестная команда.')
        return EDITING_PHOTOS
