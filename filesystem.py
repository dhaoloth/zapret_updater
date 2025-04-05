import os
import shutil
import zipfile
import requests
import time
import tkinter as tk
from tkinter import filedialog
import winshell
import string

from logger_setup import log_message
import config
from system_ops import kill_processes_using_folder # Нужна для safe_remove_folder

def get_drives():
    drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    log_message(f"Обнаружены диски: {drives}", "debug")
    return drives

def ask_for_path_dialog(title, initial_dir_key='ProgramFiles'):
    log_message(f"Запрос папки у пользователя: {title}")
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    initial_dir = os.getenv(initial_dir_key, 'C:\\')
    path = filedialog.askdirectory(title=title, initialdir=initial_dir)
    root.destroy()
    if path:
        log_message(f"Выбрана папка: {path}")
        return path
    else:
        log_message("Папка не выбрана.", 'warning')
        return None

def check_write_permission(path):
    try:
         test_file = os.path.join(path, "test_write_permission.tmp")
         with open(test_file, "w") as f: f.write("test")
         os.remove(test_file)
         return True
    except Exception as e:
         log_message(f"Ошибка записи в выбранную папку '{path}': {e}", 'error')
         log_message("Пожалуйста, выберите другую папку или убедитесь, что у вас есть права на запись.", 'error')
         return False

def safe_remove_folder(folder_path, retries=5, delay=2):
    if not os.path.exists(folder_path): return True
    log_message(f"Попытка удаления папки: {folder_path}...")
    for attempt in range(retries):
        log_message(f"Попытка {attempt + 1}/{retries} завершить процессы и удалить {folder_path}...", 'debug')
        killed = kill_processes_using_folder(folder_path)
        if killed > 0: time.sleep(1)

        try:
            shutil.rmtree(folder_path)
            time.sleep(0.5)
            if not os.path.exists(folder_path):
                log_message(f"Папка успешно удалена.")
                return True
        except PermissionError as e:
             log_message(f"Ошибка разрешений при удалении (попытка {attempt + 1}/{retries}): {e}", 'warning')
        except Exception as e:
             log_message(f"Ошибка удаления (попытка {attempt + 1}/{retries}): {e}", 'warning')
        if attempt < retries - 1: time.sleep(delay)
    log_message(f"Не удалось удалить папку {folder_path} после {retries} попыток.", 'error')
    return False

def download_file(url, target_path, description=""):
    log_message(f"Скачиваю {description} с URL: {url}")
    for attempt in range(config.MAX_RETRIES):
        try:
            response = requests.get(url, stream=True, timeout=120)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            log_message(f"Размер файла: {total_size / 1024 / 1024:.2f} MB" if total_size else "Размер файла неизвестен")
            last_print_time = time.time()

            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    current_time = time.time()
                    if total_size > 0 and (current_time - last_print_time > 1 or downloaded_size == total_size):
                        progress = downloaded_size * 100 / total_size
                        print(f"\rСкачивание {description}: {downloaded_size // 1024} / {total_size // 1024} KB ({progress:.1f}%)", end="")
                        last_print_time = current_time
            print()

            dl_size_mb = os.path.getsize(target_path)/1024/1024
            if dl_size_mb > 0.01:
                log_message(f"Файл {description} успешно скачан ({dl_size_mb:.2f} MB).")
                return True
            else:
                 log_message("Размер скачанного файла подозрительно мал. Попытка не удалась.", "warning")
                 if os.path.exists(target_path): os.remove(target_path)
                 continue
        except requests.exceptions.HTTPError as e:
             log_message(f"HTTP ошибка {e.response.status_code} при скачивании {description} (попытка {attempt + 1}): {e}", 'error')
             if e.response.status_code == 404: break
        except requests.exceptions.RequestException as e:
            log_message(f"Сетевая ошибка при скачивании {description} (попытка {attempt + 1}): {e}", 'error')
        if attempt < config.MAX_RETRIES - 1: time.sleep(config.RETRY_DELAY)
    log_message(f"Не удалось скачать файл {description} с {url}.", 'error')
    return False

def unpack_and_move(zip_path, final_target_dir):
    # Пытаемся создать временную папку рядом с final_target_dir
    try:
        base_temp_dir = os.path.dirname(final_target_dir)
        if not os.path.exists(base_temp_dir): base_temp_dir = os.getenv('TEMP', '.') # Fallback to system TEMP
    except Exception:
        base_temp_dir = os.getenv('TEMP', '.')

    temp_extract_path = os.path.join(base_temp_dir, config.TEMP_SUBDIR_EXTRACT)

    log_message(f"Распаковка архива {os.path.basename(zip_path)} во временную папку {temp_extract_path}...")

    if os.path.exists(temp_extract_path):
        if not safe_remove_folder(temp_extract_path):
            log_message(f"Не удалось очистить временную папку распаковки {temp_extract_path}.", "error")
            return False

    try:
        os.makedirs(temp_extract_path, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_path)
        log_message("Архив успешно распакован во временную папку.")
    except zipfile.BadZipFile:
        log_message(f"Ошибка: Файл {zip_path} поврежден или не является ZIP-архивом.", 'error')
        safe_remove_folder(temp_extract_path)
        return False
    except Exception as e:
        log_message(f"Критическая ошибка при распаковке архива во временную папку: {e}", 'error')
        safe_remove_folder(temp_extract_path)
        return False

    source_folder = None
    extracted_items = os.listdir(temp_extract_path)
    possible_source_folders = [d for d in extracted_items if os.path.isdir(os.path.join(temp_extract_path, d))]

    if len(possible_source_folders) == 1 and 'zapret' in possible_source_folders[0].lower():
         source_folder = os.path.join(temp_extract_path, possible_source_folders[0])
         log_message(f"Обнаружена корневая папка в архиве: {possible_source_folders[0]}. Перемещаю из нее.", 'debug')
    else:
        log_message("Предполагаю, что архив содержит файлы напрямую в корне. Перемещаю файлы как есть.", 'debug')
        source_folder = temp_extract_path


    log_message(f"Перемещение файлов из {source_folder} в {final_target_dir}...")
    try:
        os.makedirs(final_target_dir, exist_ok=True)
        for item in os.listdir(source_folder):
            s_item = os.path.join(source_folder, item)
            d_item = os.path.join(final_target_dir, item)
            if os.path.exists(d_item):
                log_message(f"Предупреждение: Элемент {item} уже существует в {final_target_dir}. Перезаписываю.", 'debug')
                if os.path.isdir(d_item): safe_remove_folder(d_item)
                else: os.remove(d_item)

            shutil.move(s_item, d_item)

        log_message("Файлы успешно перемещены в целевую папку.")
        success = True
    except Exception as e:
        log_message(f"Ошибка при перемещении файлов из временной папки в целевую: {e}", 'error')
        success = False

    log_message("Очистка временной папки распаковки...", 'debug')
    safe_remove_folder(temp_extract_path)

    return success

def create_desktop_shortcut(install_dir):
    target_bat_path = os.path.join(install_dir, config.SHORTCUT_TARGET_BAT)
    if not os.path.exists(target_bat_path):
        log_message(f"Не найден файл {config.SHORTCUT_TARGET_BAT} для создания ярлыка.", "warning")
        return False

    try:
        desktop_path = winshell.desktop()
        shortcut_path = os.path.join(desktop_path, config.SHORTCUT_NAME)
        log_message(f"Создание/обновление ярлыка на рабочем столе: {shortcut_path}")

        with winshell.shortcut(shortcut_path) as shortcut:
            shortcut.path = target_bat_path
            shortcut.working_directory = install_dir
            shortcut.description = "Запустить Zapret (обход блокировок)"
            shortcut.run_as_admin = True

        log_message("Ярлык на рабочем столе успешно создан/обновлен.", "info")
        return True
    except Exception as e:
        log_message(f"Не удалось создать ярлык на рабочем столе: {e}", "error")
        return False

def remove_desktop_shortcut():
    try:
        desktop_path = winshell.desktop()
        shortcut_path = os.path.join(desktop_path, config.SHORTCUT_NAME)
        if os.path.exists(shortcut_path):
            log_message(f"Удаляю ярлык с рабочего стола: {shortcut_path}")
            os.remove(shortcut_path)
            log_message("Ярлык успешно удален.")
            return True
        else:
            log_message("Ярлык на рабочем столе не найден.", "debug")
            return True
    except Exception as e:
        log_message(f"Не удалось удалить ярлык с рабочего стола: {e}", "error")
        return False