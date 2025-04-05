import logging
import logging.handlers
import os
import sys

logger = None

def setup_logging():
    global logger
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    try:
        appdata_path = os.getenv('LOCALAPPDATA')
        if not appdata_path:
            log_dir_base = base_dir
            print("Предупреждение: Не удалось определить папку LOCALAPPDATA. Логи будут сохраняться рядом с программой.")
        else:
            log_dir_base = os.path.join(appdata_path, 'ZapretUpdater')

        log_dir = os.path.join(log_dir_base, 'Logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'zapret_updater.log')
    except Exception as e:
        print(f"Критическая ошибка настройки папки логов: {e}. Логи будут сохраняться рядом с программой.")
        log_dir = os.path.join(base_dir, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'zapret_updater.log')

    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    print(f"Лог файл: {log_file} (Перезаписывается при каждом запуске)")

def log_message(message, level='info'):
    if logger:
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, message)
    else:
        # Fallback if logger not initialized yet
        print(f"[{level.upper()}] {message}")