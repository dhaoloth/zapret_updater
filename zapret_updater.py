# -*- coding: utf-8 -*-
import os
import re
import requests
import shutil
import zipfile
import time
import logging
import logging.handlers
import subprocess
import psutil
import ctypes
import sys
import json
import hashlib
import winreg
from datetime import datetime
from github import Github
from github.GithubException import RateLimitExceededException, GithubException, UnknownObjectException
import tkinter as tk
from tkinter import filedialog

try:
    from packaging import version as pkg_version
except ImportError:
    print("Ошибка: Не найден модуль 'packaging'. Пожалуйста, установите его: pip install packaging")
    input("Нажмите Enter для выхода...")
    sys.exit(1)
try:
    import winshell
except ImportError:
    print("Ошибка: Не найден модуль 'winshell'. Пожалуйста, установите его: pip install winshell")
    input("Нажмите Enter для выхода...")
    sys.exit(1)

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

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1024*1024*2, backupCount=1, encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    print(f"Лог файл находится здесь: {log_file}")

setup_logging()


REPO_NAME = "Flowseal/zapret-discord-youtube"
TEMP_SUBDIR_DOWNLOAD = 'zapret-temp-dl'
TEMP_SUBDIR_EXTRACT = 'zapret-temp-extract'
SIGNATURE_FILES = {
    'service_remove.bat', 'service_install.bat', 'service_status.bat',
    'discord.bat', 'general.bat', 'ipset-discord.txt',
    'list-discord.txt', 'list-general.txt', 'README.md', 'bin/winws.exe'
}
MIN_SIGNATURE_MATCH = 5
MAX_RETRIES = 3
RETRY_DELAY = 5
KEY_FILES_TO_HASH = ["bin/winws.exe", "version.txt", "general.bat"]
SHORTCUT_TARGET_BAT = "general.bat"
SHORTCUT_NAME = "Zapret General (Запуск от Админа).lnk"
REGISTRY_KEY_PATH = r"Software\ZapretUpdater"
REGISTRY_VALUE_NAME = "InstallPath"
SERVICES_TO_MANAGE = ["zapret", "WinDivert", "WinDivert14"]


def log_message(message, level='info'):
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, message)

def ask_for_user_confirmation(prompt_message):
    while True:
        try:
            response = input(f"{prompt_message} (y/n): ").lower().strip()
            if response == 'y':
                return True
            elif response == 'n':
                return False
            else:
                print("Пожалуйста, введите 'y' (да) или 'n' (нет).")
        except EOFError:
             log_message("Ввод не удался (EOF). Считаем ответ 'n'.", "warning")
             return False

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception as e:
        log_message(f"Не удалось проверить права администратора: {e}", 'error')
        return False

def run_system_command(command_args, command_desc):
    log_message(f"Выполняю команду: {' '.join(command_args)} ({command_desc})...", 'debug')
    try:
        result = subprocess.run(
            command_args,
            check=False,
            capture_output=True,
            text=True,
            encoding='cp866',
            errors='ignore',
            timeout=60,
            shell=True # SC и NET могут требовать shell
        )
        log_message(f"Код возврата '{' '.join(command_args)}': {result.returncode}", 'debug')
        if result.stdout: log_message(f"Вывод '{' '.join(command_args)}':\n{result.stdout.strip()}", 'debug')
        if result.stderr: log_message(f"Ошибка '{' '.join(command_args)}':\n{result.stderr.strip()}", 'debug')
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log_message(f"Время ожидания выполнения '{' '.join(command_args)}' истекло.", 'error')
        return -1, None, "Timeout expired"
    except Exception as e:
        log_message(f"Неожиданная ошибка при выполнении '{' '.join(command_args)}': {e}", 'error')
        return -1, None, str(e)

def remove_zapret_services():
    log_message("Попытка остановки и удаления служб Zapret и WinDivert...", 'info')
    success = True
    if not is_admin():
        log_message("Ошибка: Для управления службами нужны права Администратора.", 'error')
        return False

    for service_name in SERVICES_TO_MANAGE:
        log_message(f"Останавливаю службу {service_name}...", 'debug')
        return_code, _, stderr = run_system_command(["net", "stop", service_name], f"Остановка {service_name}")

        if return_code == 0:
            log_message(f"Служба {service_name} успешно остановлена.", 'info')
        elif return_code == 2 or "не запущена" in (stderr or "").lower() or "not started" in (stderr or "").lower(): # 1062
            log_message(f"Служба {service_name} не была запущена.", 'debug')
        else:
            log_message(f"Не удалось остановить службу {service_name} (код: {return_code}). Возможно, она не установлена.", 'warning')


        log_message(f"Удаляю службу {service_name}...", 'debug')
        return_code, _, stderr = run_system_command(["sc", "delete", service_name], f"Удаление {service_name}")

        if return_code == 0:
            log_message(f"Служба {service_name} успешно удалена.", 'info')
        elif return_code == 1060 or "не существует" in (stderr or "").lower() or "does not exist" in (stderr or "").lower():
             log_message(f"Служба {service_name} не найдена (уже удалена или не устанавливалась).", 'debug')
        else:
            log_message(f"Не удалось удалить службу {service_name} (код: {return_code}).", 'error')
            success = False

    if success:
        log_message("Завершено управление службами.", 'info')
    else:
        log_message("При управлении службами возникли ошибки.", 'warning')
    time.sleep(1)
    return success


def calculate_sha256(filepath):
    sha256_hash = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return None
    except Exception as e:
        log_message(f"Ошибка вычисления хеша для {filepath}: {e}", 'error')
        return None


def save_cached_path(path):
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH)
        winreg.SetValueEx(key, REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, path)
        winreg.CloseKey(key)
        log_message(f"Путь установки сохранен в реестре: {path}", 'debug')
    except Exception as e:
        log_message(f"Не удалось сохранить путь в реестр: {e}", 'warning')

def load_cached_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, winreg.KEY_READ)
        value, reg_type = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
        winreg.CloseKey(key)
        if reg_type == winreg.REG_SZ and value:
            log_message(f"Найден кешированный путь в реестре: {value}", 'debug')
            return value
        else:
             log_message("Кешированный путь в реестре имеет неверный тип или пуст.", 'warning')
             clear_cached_path() # Очистим некорректное значение
             return None
    except FileNotFoundError:
        log_message("Ключ реестра или значение для кешированного пути не найдено.", 'debug')
        return None
    except Exception as e:
        log_message(f"Не удалось прочитать путь из реестра: {e}", 'warning')
        return None

def clear_cached_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, winreg.KEY_WRITE)
        winreg.DeleteValue(key, REGISTRY_VALUE_NAME)
        winreg.CloseKey(key)
        log_message("Кешированный путь удален из реестра.", 'debug')
        try:
            # Попытка удалить сам ключ, если он пуст (не критично, если не удастся)
            parent_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software", 0, winreg.KEY_WRITE)
            winreg.DeleteKey(parent_key, "ZapretUpdater")
            winreg.CloseKey(parent_key)
            log_message("Ключ реестра ZapretUpdater удален.", 'debug')
        except FileNotFoundError:
            pass # Ключ уже удален или не существовал
        except Exception:
            log_message("Не удалось удалить родительский ключ реестра ZapretUpdater (возможно, не пуст).", 'debug')

    except FileNotFoundError:
        log_message("Кешированный путь или ключ реестра уже отсутствовал.", 'debug')
    except Exception as e:
        log_message(f"Не удалось удалить кешированный путь из реестра: {e}", 'warning')


def read_version_file(version_file_path):
    data = {}
    if os.path.exists(version_file_path):
        try:
            with open(version_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if ": " in line:
                        key, value = line.split(": ", 1)
                        data[key.strip()] = value.strip()
        except Exception as e:
            log_message(f"Ошибка чтения файла версии {version_file_path}: {e}", 'error')
    else:
        log_message(f"Файл версии {version_file_path} не найден.", 'debug')
    return data

def get_current_version(installed_dir):
    version_file = os.path.join(installed_dir, 'version.txt')
    version_data = read_version_file(version_file)
    return version_data.get('ver')

def get_latest_version():
    log_message("Запрашиваю информацию о последней версии с GitHub...")
    g = Github()
    retries = MAX_RETRIES
    for attempt in range(retries):
        try:
            repo = g.get_repo(REPO_NAME)
            latest_release = repo.get_latest_release()
            version = latest_release.tag_name.lstrip('v')
            log_message(f"Последняя доступная версия на GitHub: {version}")
            return version
        except RateLimitExceededException:
            wait = RETRY_DELAY * (attempt + 1)
            log_message(f"Превышен лимит запросов к GitHub API. Жду {wait} сек...", 'warning')
            time.sleep(wait)
        except UnknownObjectException:
             log_message(f"Ошибка: Репозиторий {REPO_NAME} не найден или не содержит релизов.", 'error')
             return None
        except GithubException as e:
            log_message(f"Ошибка GitHub API (попытка {attempt + 1}/{retries}): {e}", 'error')
            time.sleep(RETRY_DELAY)
        except requests.exceptions.RequestException as e:
             log_message(f"Сетевая ошибка при запросе к GitHub (попытка {attempt + 1}/{retries}): {e}", 'error')
             time.sleep(RETRY_DELAY)
    log_message("Не удалось получить последнюю версию с GitHub после нескольких попыток.", 'error')
    return None

def get_drives():
    import string
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]

def is_valid_installation(path):
    if not os.path.isdir(path): return False
    try:
        temp_paths = [os.path.realpath(os.getenv(var)) for var in ['TEMP', 'TMP'] if os.getenv(var)]
        if any(os.path.realpath(path).startswith(temp) for temp in temp_paths if temp): return False
    except Exception: pass

    try:
        found_files_set = set()
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            if os.path.isfile(item_path):
                found_files_set.add(item)
            elif os.path.isdir(item_path) and item == 'bin':
                 bin_path = item_path
                 if os.path.isdir(bin_path):
                     for bin_item in os.listdir(bin_path):
                         if os.path.isfile(os.path.join(bin_path, bin_item)):
                              found_files_set.add('bin/' + bin_item)

        matched_files = SIGNATURE_FILES.intersection(found_files_set)
        has_core_bats = {'service_remove.bat', 'service_install.bat'}.issubset(found_files_set)
        has_version = 'version.txt' in found_files_set
        has_executable = 'bin/winws.exe' in found_files_set

        is_valid = (len(matched_files) >= MIN_SIGNATURE_MATCH and has_core_bats and has_version and has_executable)

        log_message(f"Проверка валидности {path}: Найдено совпадений={len(matched_files)}/{MIN_SIGNATURE_MATCH}, Батники={has_core_bats}, Версия={has_version}, EXE={has_executable} -> {'Валидно' if is_valid else 'Невалидно'}", 'debug')
        return is_valid

    except Exception as e:
        log_message(f"Ошибка при проверке валидности папки {path}: {e}", 'debug')
        return False


def search_installation():
    log_message("Ищу существующую установку Zapret...")

    cached_path = load_cached_path()
    if cached_path and os.path.isdir(cached_path):
        log_message(f"Проверяю кешированный путь: {cached_path}", 'info')
        if is_valid_installation(cached_path):
            log_message("Кешированный путь валиден.", 'info')
            return cached_path
        else:
            log_message("Кешированный путь невалиден или указывает на некорректную установку. Очищаю кеш.", 'warning')
            clear_cached_path()


    program_files = os.getenv('ProgramFiles')
    program_files_x86 = os.getenv('ProgramFiles(x86)')
    common_paths = []
    if program_files: common_paths.append(program_files)
    if program_files_x86 and program_files_x86 != program_files: common_paths.append(program_files_x86)
    common_paths.append('C:\\Zapret') # Добавим стандартный путь для примера

    for common_path_base in common_paths:
        log_message(f"Проверяю стандартную папку/путь: {common_path_base}", 'debug')
        if os.path.isdir(common_path_base):
            # Проверяем сам путь
            if 'zapret' in common_path_base.lower() and is_valid_installation(common_path_base):
                 log_message(f"Найдена установка в стандартном пути: {common_path_base}")
                 save_cached_path(common_path_base)
                 return common_path_base
            # Проверяем подпапки с именем zapret внутри Program Files
            if common_path_base == program_files or common_path_base == program_files_x86:
                try:
                    for entry in os.scandir(common_path_base):
                        if entry.is_dir(follow_symlinks=False) and 'zapret' in entry.name.lower():
                            if is_valid_installation(entry.path):
                                log_message(f"Найдена установка в подпапке стандартного пути: {entry.path}")
                                save_cached_path(entry.path)
                                return entry.path
                except OSError as e:
                    log_message(f"Ошибка доступа к {common_path_base}: {e}", 'warning')


    log_message("Поиск в стандартных и кешированных путях не дал результатов. Начинаю ПОЛНЫЙ поиск по всем дискам...", 'info')
    for drive in get_drives():
        log_message(f"Проверяю диск {drive}...", 'debug')
        try:
            for root, dirs, files in os.walk(drive, topdown=True):
                original_dirs_count = len(dirs)
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in [
                    'windows', '$recycle.bin', 'system volume information', 'programdata',
                    'appdata', 'recovery', 'config.msi', 'games', 'steam', 'users',
                    'program files', 'program files (x86)',
                    'intel', 'amd', 'nvidia', '$windows.~ws', '$windows.~bt',
                    'perflogs', 'msocache', 'public', 'drivers', 'temp', 'tmp', '__pycache__'
                    ]
                ]

                log_message(f"Полный скан: Проверяю содержимое папки {root}", 'debug')
                if is_valid_installation(root):
                    log_message(f"Найдена установка (через полный скан): {root}")
                    save_cached_path(root)
                    return root

                # Ограничение глубины сканирования для ускорения
                # current_depth = root.count(os.sep) - drive.count(os.sep)
                # if current_depth >= 6:
                #    log_message(f"Ограничение глубины: Пропускаю дальнейший спуск в {root}", 'debug')
                #    dirs[:] = []

        except Exception as e:
             log_message(f"Ошибка доступа или другая проблема при сканировании {drive} в {root if 'root' in locals() else ''}: {e}", 'debug')
             pass

    log_message("Существующая установка Zapret не найдена (после полного сканирования).", 'warning')
    return None


def ask_for_installation_path(title="Выберите папку для установки Zapret"):
    log_message(f"Пожалуйста, выберите папку в появившемся окне.")
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    initial_dir = os.getenv('ProgramFiles', 'C:\\')
    path = filedialog.askdirectory(title=title, initialdir=initial_dir)
    root.destroy()
    if path:
        log_message(f"Выбрана папка: {path}")
        try:
             test_file = os.path.join(path, "test_write_zapret.tmp")
             with open(test_file, "w") as f: f.write("test")
             os.remove(test_file)
             return path
        except Exception as e:
             log_message(f"Ошибка записи в выбранную папку '{path}': {e}", 'error')
             log_message("Пожалуйста, выберите другую папку или убедитесь, что у вас есть права на запись.", 'error')
             return None
    else:
        log_message("Папка не выбрана.", 'warning')
        return None

def kill_processes_using_folder(folder_path):
    killed_count = 0
    try:
        folder_realpath = os.path.realpath(folder_path)
        if not os.path.exists(folder_realpath): return 0
    except Exception as e:
         log_message(f"Не удалось получить реальный путь для {folder_path}: {e}", "error")
         return 0

    for proc in psutil.process_iter(['pid', 'name', 'open_files', 'exe', 'cmdline']):
        try:
            proc_info = proc.info
            # Проверка исполняемого файла
            exe_path = proc_info.get('exe')
            if exe_path and os.path.realpath(exe_path).startswith(folder_realpath):
                 log_message(f"Обнаружен процесс {proc_info['name']} (PID: {proc_info['pid']}), запущенный из {folder_realpath}. Завершаю...", 'warning')
                 proc.kill()
                 killed_count += 1
                 time.sleep(0.5)
                 continue

            # Проверка открытых файлов/хендлов
            open_files = proc_info.get('open_files')
            if open_files:
                for file_handle in open_files:
                    try:
                        if os.path.realpath(file_handle.path).startswith(folder_realpath):
                            log_message(f"Обнаружен процесс {proc_info['name']} (PID: {proc_info['pid']}), использующий файл в {folder_realpath}. Завершаю...", 'warning')
                            proc.kill()
                            killed_count += 1
                            time.sleep(0.5)
                            break
                    except Exception: pass # Ошибка доступа к пути файла хендла
                if proc.is_running(): # Если процесс еще жив после проверки файлов
                    # Проверка командной строки (для .bat файлов, запущенных через cmd.exe)
                    cmdline = proc_info.get('cmdline')
                    if cmdline and any(folder_realpath in arg for arg in cmdline):
                         log_message(f"Обнаружен процесс {proc_info['name']} (PID: {proc_info['pid']}), в командной строке которого есть путь {folder_realpath}. Завершаю...", 'warning')
                         proc.kill()
                         killed_count += 1
                         time.sleep(0.5)

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess): continue
        except Exception as e: log_message(f"Ошибка при проверке процесса {proc_info.get('name', '?')} (PID: {proc.pid}): {e}", 'error')
    if killed_count > 0: log_message(f"Завершено процессов: {killed_count}.", 'info')
    return killed_count


def safe_remove_folder(folder_path, retries=5, delay=2):
    if not os.path.exists(folder_path): return True
    log_message(f"Попытка удаления папки: {folder_path}...")
    for attempt in range(retries):
        log_message(f"Попытка {attempt + 1}/{retries} завершить процессы и удалить {folder_path}...", 'debug')
        killed = kill_processes_using_folder(folder_path)
        if killed > 0: time.sleep(1) # Дать время на освобождение ресурсов

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

def download_release_zip(version_to_download, target_zip_path):
    zip_filename = f"zapret-discord-youtube-{version_to_download}.zip"
    urls_to_try = [
        f"https://github.com/{REPO_NAME}/releases/download/v{version_to_download}/{zip_filename}",
        f"https://github.com/{REPO_NAME}/releases/download/{version_to_download}/{zip_filename}"
    ]
    for url in urls_to_try:
        log_message(f"Пытаюсь скачать с URL: {url}")
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, stream=True, timeout=120) # Увеличил таймаут
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                downloaded_size = 0
                log_message(f"Размер архива: {total_size / 1024 / 1024:.2f} MB" if total_size else "Размер архива неизвестен")
                last_print_time = time.time()

                with open(target_zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        current_time = time.time()
                        if total_size > 0 and (current_time - last_print_time > 1 or downloaded_size == total_size):
                            progress = downloaded_size * 100 / total_size
                            print(f"\rСкачивание: {downloaded_size // 1024} / {total_size // 1024} KB ({progress:.1f}%)", end="")
                            last_print_time = current_time
                print()

                dl_size_mb = os.path.getsize(target_zip_path)/1024/1024
                if dl_size_mb > 0.1:
                     # Проверка целостности архива
                     log_message("Проверяю целостность скачанного архива...")
                     try:
                         with zipfile.ZipFile(target_zip_path) as zf:
                             bad_file = zf.testzip()
                             if bad_file:
                                 log_message(f"Ошибка: Скачанный архив поврежден (файл: {bad_file}). Удаляю.", "error")
                                 os.remove(target_zip_path)
                                 return False # Продолжаем пробовать другие URL / попытки
                             else:
                                 log_message(f"Архив версии {version_to_download} успешно скачан и проверен ({dl_size_mb:.2f} MB).")
                                 return True
                     except Exception as e:
                          log_message(f"Ошибка проверки ZIP-архива: {e}. Удаляю.", "error")
                          if os.path.exists(target_zip_path): os.remove(target_zip_path)
                          return False
                else:
                     log_message("Размер скачанного файла подозрительно мал. Попытка не удалась.", "warning")
                     if os.path.exists(target_zip_path): os.remove(target_zip_path)
                     continue
            except requests.exceptions.HTTPError as e:
                 log_message(f"HTTP ошибка {e.response.status_code} (попытка {attempt + 1}): {e}", 'error')
                 if e.response.status_code == 404: break
            except requests.exceptions.RequestException as e:
                log_message(f"Сетевая ошибка (попытка {attempt + 1}): {e}", 'error')
            if attempt < MAX_RETRIES - 1: time.sleep(RETRY_DELAY)
    log_message(f"Не удалось скачать архив версии {version_to_download}.", 'error')
    return False


def unpack_and_move(zip_path, final_target_dir):
    base_temp_dir = os.path.dirname(final_target_dir) # Распаковываем рядом
    temp_extract_path = os.path.join(base_temp_dir, TEMP_SUBDIR_EXTRACT)

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

    # Найти папку с реальными файлами внутри temp_extract_path
    extracted_items = os.listdir(temp_extract_path)
    if len(extracted_items) != 1 or not os.path.isdir(os.path.join(temp_extract_path, extracted_items[0])):
        # Если внутри архива нет одной корневой папки, а сразу файлы
        log_message("Архив содержит файлы напрямую в корне. Перемещаю файлы как есть.", 'debug')
        source_folder = temp_extract_path
    else:
        # Если внутри архива есть корневая папка (стандартный случай GitHub)
        source_folder = os.path.join(temp_extract_path, extracted_items[0])
        log_message(f"Обнаружена корневая папка в архиве: {extracted_items[0]}. Перемещаю из нее.", 'debug')


    log_message(f"Перемещение файлов из {source_folder} в {final_target_dir}...")
    try:
        os.makedirs(final_target_dir, exist_ok=True) # Убедимся, что целевая папка существует
        # Перемещаем содержимое source_folder в final_target_dir
        for item in os.listdir(source_folder):
            s_item = os.path.join(source_folder, item)
            d_item = os.path.join(final_target_dir, item)
            if os.path.isdir(s_item):
                shutil.move(s_item, d_item)
            else:
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
    target_bat_path = os.path.join(install_dir, SHORTCUT_TARGET_BAT)
    if not os.path.exists(target_bat_path):
        log_message(f"Не найден файл {SHORTCUT_TARGET_BAT} для создания ярлыка.", "warning")
        return False

    try:
        desktop_path = winshell.desktop()
        shortcut_path = os.path.join(desktop_path, SHORTCUT_NAME)
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
        shortcut_path = os.path.join(desktop_path, SHORTCUT_NAME)
        if os.path.exists(shortcut_path):
            log_message(f"Удаляю ярлык с рабочего стола: {shortcut_path}")
            os.remove(shortcut_path)
            # winshell.delete(shortcut_path) # Можно и так
            log_message("Ярлык успешно удален.")
            return True
        else:
            log_message("Ярлык на рабочем столе не найден.", "debug")
            return True
    except Exception as e:
        log_message(f"Не удалось удалить ярлык с рабочего стола: {e}", "error")
        return False


def perform_install_or_update(version_to_install, install_dir, is_update=False):
    action = "Обновление" if is_update else "Установка"
    log_message(f"Начинаю {action.lower()} Zapret до версии {version_to_install} в папку: {install_dir}")

    temp_base_path = os.getenv('TEMP', '.')
    temp_download_path = os.path.join(temp_base_path, TEMP_SUBDIR_DOWNLOAD)
    os.makedirs(temp_download_path, exist_ok=True)
    zip_path = os.path.join(temp_download_path, f"zapret-{version_to_install}.zip")

    if not download_release_zip(version_to_install, zip_path):
        safe_remove_folder(temp_download_path)
        return False

    if is_update:
        remove_zapret_services()
        log_message("Пытаюсь завершить процессы, использующие папку установки...")
        kill_processes_using_folder(install_dir)
        log_message("Удаляю старую версию...")
        if not safe_remove_folder(install_dir):
            log_message("Критическая ошибка: Не удалось удалить старую версию.", 'error')
            safe_remove_folder(temp_download_path)
            return False
    else: # Первая установка или починка с нуля
        # На всякий случай удалим папку, если там что-то есть (после подтверждения)
        if os.path.exists(install_dir):
            if not safe_remove_folder(install_dir):
                log_message(f"Критическая ошибка: Не удалось очистить целевую папку {install_dir} перед установкой.", 'error')
                safe_remove_folder(temp_download_path)
                return False

    if not unpack_and_move(zip_path, install_dir):
        safe_remove_folder(temp_download_path)
        log_message(f"Критическая ошибка: Не удалось распаковать/переместить новую версию. Папка '{install_dir}' может быть повреждена или отсутствовать.", 'error')
        # Попытаться восстановить? Сложно. Лучше сообщить об ошибке.
        safe_remove_folder(install_dir) # Удаляем возможно частично созданную папку
        return False

    create_desktop_shortcut(install_dir)

    log_message(f"Очистка временных файлов {action.lower()}...")
    safe_remove_folder(temp_download_path)

    log_message("-" * 30)
    if is_update:
        log_message(f"УСПЕХ! Zapret успешно обновлен до версии {version_to_install} в '{install_dir}'.")
        log_message(f"Ярлык '{SHORTCUT_NAME}' на рабочем столе обновлен.")
        log_message("Если вы использовали службу автозапуска, ее нужно переустановить (service_install.bat).")
    else:
        log_message(f"УСПЕХ! Zapret версии {version_to_install} успешно установлен в '{install_dir}'.")
        log_message(f"На вашем рабочем столе создан ярлык '{SHORTCUT_NAME}'.")
        log_message("Вы можете запустить его для обхода блокировок.")
        log_message("Для настройки автозапуска используйте service_install.bat (от им. Администратора).")
    log_message("-" * 30)

    save_cached_path(install_dir) # Обновляем кеш пути
    return True


def perform_uninstall(install_dir):
    log_message(f"Начинаю удаление Zapret из папки: {install_dir}")
    if not os.path.isdir(install_dir):
        log_message("Папка установки не найдена. Возможно, программа уже удалена.", "warning")
        clear_cached_path()
        remove_desktop_shortcut()
        return True

    remove_zapret_services()
    kill_processes_using_folder(install_dir)
    remove_desktop_shortcut()

    if safe_remove_folder(install_dir):
        log_message("Папка установки успешно удалена.")
        clear_cached_path()
        log_message("-" * 30)
        log_message("УСПЕХ! Zapret успешно удален.")
        log_message("Службы (если были) остановлены и удалены, ярлык удален.")
        log_message("-" * 30)
        return True
    else:
        log_message("Ошибка: Не удалось полностью удалить папку установки.", "error")
        log_message("Возможно, некоторые файлы используются. Попробуйте перезагрузить компьютер и удалить папку вручную.", "error")
        return False


def show_main_menu(installed_dir, current_version, latest_version):
    while True:
        print("\n--- Меню Управления Zapret ---")
        print(f" Установлен в: {installed_dir}")
        print(f" Текущая версия: {current_version if current_version else 'Неизвестно'}")
        print(f" Последняя версия: {latest_version if latest_version else 'Неизвестно'}")
        print("-" * 30)
        print("1. Проверить и установить обновления (если доступны)")
        print("2. Переустановить/Починить (установить последнюю версию)")
        print("3. Удалить Zapret с компьютера")
        print("0. Выход")
        print("-" * 30)

        choice = input("Выберите действие (введите номер): ").strip()

        if choice == '1':
            update_needed = False
            reason = "Неизвестно"
            if not current_version:
                update_needed = True
                reason = "текущая версия не определена"
            elif not latest_version:
                log_message("Не удалось получить последнюю версию для сравнения.", "warning")
                print("Не удалось проверить наличие обновлений.")
                continue
            elif latest_version != current_version:
                 try:
                     if pkg_version.parse(latest_version) > pkg_version.parse(current_version):
                         update_needed = True
                         reason = f"доступна новая версия {latest_version}"
                     else:
                         reason = f"установлена последняя или более новая версия ({current_version})"
                 except Exception as e:
                     log_message(f"Ошибка сравнения версий: {e}. Предлагаем обновиться.", "warning")
                     update_needed = True
                     reason = "ошибка сравнения версий"
            else:
                reason = f"установлена последняя версия ({current_version})"

            log_message(f"Результат проверки обновлений: {reason}.")
            if update_needed:
                if ask_for_user_confirmation(f"Доступно обновление до версии {latest_version} ({reason}). Начать обновление?"):
                    perform_install_or_update(latest_version, installed_dir, is_update=True)
                else:
                    log_message("Обновление отменено пользователем.")
            else:
                print("Обновление не требуется. У вас установлена последняя версия.")
                log_message("Обновление не требуется.")
            input("Нажмите Enter для возврата в меню...") # Пауза после действия

        elif choice == '2':
            if not latest_version:
                log_message("Не удалось получить последнюю версию для переустановки.", "error")
                print("Невозможно выполнить переустановку: не удалось определить последнюю версию.")
                continue
            if ask_for_user_confirmation(f"Вы уверены, что хотите переустановить Zapret (версия {latest_version}) в папку '{installed_dir}'? Существующие файлы будут удалены."):
                perform_install_or_update(latest_version, installed_dir, is_update=True) # Используем логику обновления для очистки
            else:
                log_message("Переустановка отменена пользователем.")
            input("Нажмите Enter для возврата в меню...")

        elif choice == '3':
            if ask_for_user_confirmation(f"ВНИМАНИЕ! Вы уверены, что хотите ПОЛНОСТЬЮ удалить Zapret из папки '{installed_dir}', включая службы и ярлык?"):
                perform_uninstall(installed_dir)
                return True # Выход из меню и программы после удаления
            else:
                log_message("Удаление отменено пользователем.")
            input("Нажмите Enter для возврата в меню...")

        elif choice == '0':
            log_message("Выход из программы по выбору пользователя.")
            return False # Просто выход из меню

        else:
            print("Неверный выбор. Пожалуйста, введите номер из меню.")


def run_main_logic():
    log_message("-" * 50)
    log_message("Запуск установщика/обновления Zapret для Discord/YouTube")
    log_message("Репозиторий: dhaoloth/zapret_updater")
    log_message("Версия скрипта: 1.0.3")
    log_message(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_message("-" * 50)

    if not is_admin():
         log_message("Критическая ошибка: Скрипт запущен без прав Администратора!", "critical")
         log_message("Пожалуйста, перезапустите скрипт с правами Администратора.", "critical")
         return

    installed_dir = search_installation()
    latest_version = get_latest_version()

    if not installed_dir:
        log_message("Программа Zapret не найдена на этом компьютере.")
        if not latest_version:
             log_message("Не удалось получить информацию о последней версии с GitHub.", 'error')
             log_message("Установка невозможна. Проверьте интернет-соединение и доступность GitHub.", 'error')
             return

        if ask_for_user_confirmation(f"Хотите установить последнюю версию ({latest_version}) сейчас?"):
            chosen_path = ask_for_installation_path(title="Выберите папку для НОВОЙ установки Zapret")
            if chosen_path:
                if os.path.exists(chosen_path) and os.listdir(chosen_path):
                     if not ask_for_user_confirmation(f"ВНИМАНИЕ: Папка '{chosen_path}' не пуста. Хотите удалить ее содержимое и продолжить установку?"):
                         log_message("Установка отменена пользователем из-за непустой папки.")
                         return

                perform_install_or_update(latest_version, chosen_path, is_update=False)
            else:
                log_message("Папка для установки не выбрана. Установка отменена.")
        else:
            log_message("Установка отменена пользователем.")
    else:
        current_version = get_current_version(installed_dir)
        if not current_version:
            log_message("Не удалось определить версию установленной программы (файл version.txt отсутствует или поврежден).", "warning")

        exit_after_menu = show_main_menu(installed_dir, current_version, latest_version)
        if exit_after_menu:
             return # Выход из программы (например, после удаления)


if __name__ == "__main__":
    elevated_param = '--elevated'
    run_as_admin_requested = False

    # --- Логика запроса прав Администратора ---
    if elevated_param not in sys.argv and not is_admin():
        log_message("Для работы требуются права Администратора.", 'warning')
        log_message("Запрос на повышение прав (UAC)...", 'info')
        time.sleep(1)

        try:
            script_path = os.path.abspath(sys.argv[0])
            params = [elevated_param] + sys.argv[1:]
            params_string = subprocess.list2cmdline(params)

            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script_path}" {params_string}', None, 1
            )

            if ret <= 32:
                error_codes = { 0: "Недостаточно ресурсов.", 2: "Файл не найден.", 3: "Путь не найден.", 5: "Отказано в доступе (UAC?).", 8: "Недостаточно памяти.", 11: "Неверный формат EXE.", 1223: "Операция отменена пользователем (UAC)." }
                error_message = error_codes.get(ret, f"Неизвестная ошибка ShellExecuteW (код {ret})")
                log_message(f"Не удалось запустить процесс с повышенными правами: {error_message}", 'error')
                print(f"\nОшибка получения прав Администратора: {error_message}")
                if ret != 1223: print("Попробуйте запустить файл вручную 'От имени администратора'.")
                input("Нажмите Enter для выхода...")
                sys.exit(1) # Выход из оригинального процесса
            else:
                log_message("Запрос на повышение прав отправлен. Исходный процесс завершается...", 'info')
                sys.exit(0) # Успешный запуск нового процесса, старый завершаем
        except Exception as e:
            log_message(f"Исключение при попытке перезапуска с повышением прав: {e}", 'critical')
            logger.exception(e)
            print("\nПроизошла ошибка при попытке запросить права Администратора.")
            input("Нажмите Enter для выхода...")
            sys.exit(1)

    # --- Если мы здесь, значит права есть (либо были, либо получены через перезапуск) ---
    if elevated_param in sys.argv:
        sys.argv.remove(elevated_param)
        log_message("Скрипт перезапущен с правами администратора.", 'info')
    elif is_admin():
         log_message("Скрипт уже запущен с правами администратора.", 'info')

    try:
        run_main_logic()
    except Exception as e:
        log_message("Произошла критическая непредвиденная ошибка:", 'critical')
        logger.exception(e)
        print("\nПроизошла критическая ошибка. Подробности в лог-файле.")

    print("\nРабота программы завершена.")
    input("Нажмите Enter для закрытия окна...")