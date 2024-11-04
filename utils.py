import re
import datetime
import os
import shutil

def sanitize_pack_name(pack_name: str, bot_username: str) -> str:
    """Приводит имя стикерпака к требованиям Telegram."""
    pack_name = pack_name.lower()
    pack_name = re.sub(r'[^a-z0-9_]+', '', pack_name)
    pack_name = f"{pack_name[:32]}_by_{bot_username}"  # Обрезаем до 32 символов + имя бота
    return pack_name

def log_error(error_message, traceback_info=None, user_id=None):
    """Записывает ошибку в файл."""
    try:
        timestamp = datetime.datetime.now()
        timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        if not os.path.exists("logs"):
            os.makedirs("logs")
        if user_id is not None:
            user_log_dir = os.path.join("logs", str(user_id))
            os.makedirs(user_log_dir, exist_ok=True)
            error_id = int(timestamp.timestamp())
            log_filename = os.path.join(user_log_dir, f"{user_id}_{error_id}.log")
        else:
            log_filename = os.path.join("logs", f"errors_{timestamp.strftime('%Y%m%d%H%M%S')}.log")
        with open(log_filename, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp_str}] - {error_message}\n")
            if traceback_info:
                log_file.write(f"Traceback:\n{traceback_info}\n")
        return log_filename
    except Exception as e:
        print(f"Не удалось записать лог ошибки: {str(e)}")
        return None

# utils.py

import logging

def log_info(message: str):
    """Записывает общую информацию в лог."""
    logging.info(message)


def cleanup_temp_files():
    """Очищает временные файлы и директории."""
    try:
        if os.path.exists('temp.zip'):
            os.remove('temp.zip')
    except Exception as e:
        log_error(f"Ошибка при очистке временных файлов: {str(e)}")
