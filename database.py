import sqlite3
import re
import traceback
from contextlib import closing
from telegram import Bot
from telegram.error import TelegramError
from utils import log_error
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'stickers.db')

def initialize_db():
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        photo_counter INTEGER DEFAULT 0,
                        video_counter INTEGER DEFAULT 0
                    )
                ''')
                conn.execute('''
                                    CREATE TABLE IF NOT EXISTS sticker_packs (
                                        pack_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                        user_id INTEGER,
                                        pack_name TEXT,
                                        author_name TEXT,
                                        pack_link TEXT,
                                        is_private INTEGER,
                                        FOREIGN KEY(user_id) REFERENCES users(user_id)
                                    )
                                ''')
                # Добавляем новую таблицу для фотографий пользователей
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS user_photos (
                        photo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        photo_path TEXT,
                        photo_name TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(user_id)
                    )
                ''')
                conn.execute('''
                                    CREATE TABLE IF NOT EXISTS user_messages (
                                        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                        user_id INTEGER,
                                        message_text TEXT,
                                        has_error INTEGER,
                                        error_log_link TEXT,
                                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                        FOREIGN KEY(user_id) REFERENCES users(user_id)
                                    )
                                ''')
                conn.execute('''
                                    CREATE TABLE IF NOT EXISTS admins (
                                        admin_id INTEGER PRIMARY KEY
                                    )
                                ''')
                conn.execute('''
                                    CREATE TABLE IF NOT EXISTS user_videos (
                                        video_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                        user_id INTEGER,
                                        video_path TEXT,
                                        video_name TEXT,
                                        FOREIGN KEY(user_id) REFERENCES users(user_id)
                                    )
                                ''')
    except sqlite3.Error as e:
        log_error(f"Ошибка инициализации базы данных: {e}")
        raise

def get_and_increment_photo_counter(user_id: int):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT photo_counter FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if result:
                counter = result[0] + 1
                cursor.execute('UPDATE users SET photo_counter = ? WHERE user_id = ?', (counter, user_id))
            else:
                counter = 1
                cursor.execute('INSERT INTO users (user_id, username, photo_counter) VALUES (?, ?, ?)', (user_id, '', counter))
            conn.commit()
            return counter
    except sqlite3.Error as e:
        log_error(f"Ошибка при обновлении photo_counter для пользователя {user_id}: {e}")
        return None

def get_and_increment_video_counter(user_id: int):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT video_counter FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if result:
                counter = result[0] + 1
                cursor.execute('UPDATE users SET video_counter = ? WHERE user_id = ?', (counter, user_id))
            else:
                counter = 1
                cursor.execute('INSERT INTO users (user_id, username, video_counter) VALUES (?, ?, ?)', (user_id, '', counter))
            conn.commit()
            return counter
    except sqlite3.Error as e:
        log_error(f"Ошибка при обновлении video_counter для пользователя {user_id}: {e}")
        return None


def add_user_video(user_id: int, video_path: str, video_name: str):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute('''
                    INSERT INTO user_videos (user_id, video_path, video_name)
                    VALUES (?, ?, ?)
                ''', (user_id, video_path, video_name))
    except sqlite3.Error as e:
        log_error(f"Ошибка добавления видео для пользователя {user_id}: {e}")

def is_admin(user_id: int) -> bool:
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM admins WHERE admin_id = ?', (user_id,))
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        log_error(f"Ошибка проверки администратора {user_id}: {e}")
        return False

def get_users(offset=0, limit=10):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username FROM users LIMIT ? OFFSET ?
            ''', (limit, offset))
            return cursor.fetchall()
    except sqlite3.Error as e:
        log_error(f"Ошибка получения списка пользователей: {e}")
        return []

def get_public_packs(offset=0, limit=10):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT pack_id, pack_name, author_name, pack_link FROM sticker_packs
                WHERE is_private = 0
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            return cursor.fetchall()
    except sqlite3.Error as e:
        log_error(f"Ошибка получения публичных стикерпаков: {e}")
        return []

def update_pack_name(pack_id: int, new_name: str):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute('''
                    UPDATE sticker_packs SET pack_name = ? WHERE pack_id = ?
                ''', (new_name, pack_id))
    except sqlite3.Error as e:
        log_error(f"Ошибка обновления названия стикерпака {pack_id}: {e}")

def replace_stickers(pack_id: int, new_image_files: list, new_emojis: list):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                # Здесь можно реализовать логику замены стикеров
                # Например, удалить старые стикеры и добавить новые через Telegram API
                pass  # Реализуйте по необходимости
    except sqlite3.Error as e:
        log_error(f"Ошибка замены стикеров для стикерпака {pack_id}: {e}")

async def delete_sticker_pack(pack_id: int, user_id: int, bot: Bot) -> bool:
    """
    Удаляет стикерпак из базы данных и через Telegram API.

    Args:
        pack_id (int): Идентификатор стикерпака.
        user_id (int): Идентификатор пользователя.
        bot (Bot): Экземпляр Telegram Bot.

    Returns:
        bool: True, если удаление прошло успешно, иначе False.
    """
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT pack_link FROM sticker_packs WHERE pack_id = ? AND user_id = ?
                ''', (pack_id, user_id))
                result = cursor.fetchone()
                if result:
                    pack_link = result[0]

                    # Извлекаем имя стикерпака из ссылки
                    match = re.search(r'/addstickers/([a-zA-Z0-9_]+)', pack_link)
                    if match:
                        pack_name = match.group(1)
                        try:
                            # Удаляем стикерпак через Telegram API
                            await bot.delete_sticker_set(pack_name)
                        except TelegramError as e:
                            log_error(f"Не удалось удалить стикерпак {pack_name}: {e}")
                            return False

                        try:
                            # Удаляем запись из базы данных
                            cursor.execute('''
                                DELETE FROM sticker_packs WHERE pack_id = ? AND user_id = ?
                            ''', (pack_id, user_id))
                            return True
                        except sqlite3.Error as db_error:
                            log_error(f"Ошибка при удалении записи с pack_id={pack_id}: {db_error}")
                            return False
                    else:
                        log_error(f"Некорректный формат pack_link: {pack_link}")
                        return False
                else:
                    log_error(f"Стикерпак с pack_id={pack_id} и user_id={user_id} не найден.")
                    return False
    except Exception as e:
        log_error(f"Ошибка в delete_sticker_pack: {str(e)}", traceback.format_exc())
        return False



def get_all_packs(offset=0, limit=10):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT pack_id, pack_name, author_name, pack_link FROM sticker_packs
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            return cursor.fetchall()
    except sqlite3.Error as e:
        log_error(f"Ошибка получения списка всех стикерпаков: {e}")
        return []


def get_pack_by_id(pack_id: int):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM sticker_packs WHERE pack_id = ?
            ''', (pack_id,))
            return cursor.fetchone()
    except sqlite3.Error as e:
        log_error(f"Ошибка получения стикерпака по ID {pack_id}: {e}")
        return None


def add_user_message(user_id: int, message_text: str, has_error: bool, error_log_link: str = None):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute('''
                    INSERT INTO user_messages (user_id, message_text, has_error, error_log_link)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, message_text, int(has_error), error_log_link))
    except sqlite3.Error as e:
        log_error(f"Ошибка добавления сообщения для пользователя {user_id}: {e}")


def add_user_photo(user_id: int, photo_path: str, photo_name: str):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute('''
                    INSERT INTO user_photos (user_id, photo_path, photo_name)
                    VALUES (?, ?, ?)
                ''', (user_id, photo_path, photo_name))
    except sqlite3.Error as e:
        log_error(f"Ошибка добавления фотографии для пользователя {user_id}: {e}")


def add_user(user_id: int, username: str):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute('''
                    INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)
                ''', (user_id, username))
    except sqlite3.Error as e:
        log_error(f"Ошибка добавления пользователя {user_id}: {e}")

def add_sticker_pack(user_id: int, pack_name: str, author_name: str, pack_link: str, is_private: bool):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute('''
                    INSERT INTO sticker_packs (user_id, pack_name, author_name, pack_link, is_private)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, pack_name, author_name, pack_link, int(is_private)))
    except sqlite3.Error as e:
        log_error(f"Ошибка добавления стикерпака для пользователя {user_id}: {e}")


def get_user_packs(user_id: int):
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT pack_id, pack_name, author_name, pack_link FROM sticker_packs
                WHERE user_id = ?
            ''', (user_id,))
            return cursor.fetchall()
    except sqlite3.Error as e:
        log_error(f"Ошибка получения стикерпаков для пользователя {user_id}: {e}")
        return []

async def delete_sticker_pack(pack_id: int, user_id: int, bot: Bot) -> bool:
    """
    Удаляет стикерпак из базы данных и через Telegram API.

    Args:
        pack_id (int): Идентификатор стикерпака.
        user_id (int): Идентификатор пользователя.
        bot (Bot): Экземпляр Telegram Bot.

    Returns:
        bool: True, если удаление прошло успешно, иначе False.
    """
    try:
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT pack_link FROM sticker_packs WHERE pack_id = ? AND user_id = ?
                ''', (pack_id, user_id))
                result = cursor.fetchone()
                if result:
                    pack_link = result[0]

                    # Извлекаем имя стикерпака из ссылки
                    match = re.search(r'/addstickers/([a-zA-Z0-9_]+)', pack_link)
                    if match:
                        pack_name = match.group(1)
                        try:
                            # Удаляем стикерпак через Telegram API
                            await bot.delete_sticker_set(pack_name)
                        except TelegramError as e:
                            log_error(f"Не удалось удалить стикерпак {pack_name}: {e}")
                            return False

                        try:
                            # Удаляем запись из базы данных
                            cursor.execute('''
                                DELETE FROM sticker_packs WHERE pack_id = ? AND user_id = ?
                            ''', (pack_id, user_id))
                            return True
                        except sqlite3.Error as db_error:
                            log_error(f"Ошибка при удалении записи с pack_id={pack_id}: {db_error}")
                            return False
                    else:
                        log_error(f"Некорректный формат pack_link: {pack_link}")
                        return False
                else:
                    log_error(f"Стикерпак с pack_id={pack_id} и user_id={user_id} не найден.")
                    return False
    except Exception as e:
        log_error(f"Ошибка в delete_sticker_pack: {str(e)}", traceback.format_exc())
        return False

if __name__ == '__main__':
    initialize_db()
    print("База данных инициализирована.")