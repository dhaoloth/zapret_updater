# -*- coding: utf-8 -*-
import os
import re
import requests
import shutil
import zipfile
import time
import logging
import subprocess
import psutil
import ctypes
import sys
import json
import hashlib
from datetime import datetime
from github import Github
from github.GithubException import RateLimitExceededException, GithubException, UnknownObjectException
import tkinter as tk
from tkinter import filedialog

# --- ЗАВИСИМОСТИ ---
# pip install requests PyGithub psutil packaging winshell

# --- ПОПЫТКА ИМПОРТА С УСТАНОВКОЙ ПОДСКАЗОК ---
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

# --- КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ ---
if getattr(sys, 'frozen', False): # Определение пути при запуске из EXE
    BASE_DIR = os.path.dirname(sys.executable)
else: # Определение пути при запуске из PY
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'zapret_updater.log')

# Настройка логирования (файл + консоль)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
# Файловый обработчик
file_handler = logging.FileHandler(LOG_FILE, 'a', 'utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)
# Консольный обработчик
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)
# Добавляем обработчики к корневому логгеру
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


# --- КОНФИГУРАЦИЯ СКРИПТА ---
REPO_NAME = "Flowseal/zapret-discord-youtube"
TEMP_SUBDIR = 'zapret-temp'
SIGNATURE_FILES = { # Файлы для определения существующей установки
    'service_remove.bat', 'service_install.bat', 'service_status.bat',
    'discord.bat', 'general.bat', 'ipset-discord.txt',
    'list-discord.txt', 'list-general.txt', 'README.md', 'bin/winws.exe'
}
MIN_SIGNATURE_MATCH = 5 # Минимальное кол-во файлов для подтверждения установки
MAX_RETRIES = 3
RETRY_DELAY = 5
LOCAL_HASH_FILE = os.path.join(BASE_DIR, 'local_zapret_hashes.json') # Файл для хешей
KEY_FILES_TO_HASH = ["bin/winws.exe", "service_install.bat", "service_remove.bat", "version.txt", "general.bat"] # Файлы для проверки целостности
SHORTCUT_TARGET_BAT = "general.bat" # Какой батник использовать для ярлыка
SHORTCUT_NAME = "Zapret General (Запуск от Админа).lnk" # Имя ярлыка


# --- ОСНОВНЫЕ ФУНКЦИИ ---

def log_message(message, level='info'):
    """Логирует сообщение с нужным уровнем."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, message)

def ask_for_user_confirmation(prompt_message):
    """Запрашивает у пользователя подтверждение (y/n)."""
    while True:
        try:
            response = input(f"{prompt_message} (y/n): ").lower().strip()
            if response == 'y':
                return True
            elif response == 'n':
                return False
            else:
                print("Пожалуйста, введите 'y' (да) или 'n' (нет).")
        except EOFError: # Обработка Ctrl+Z или если stdin закрыт
             log_message("Ввод не удался (EOF). Считаем ответ 'n'.", "warning")
             return False

def is_admin():
    """Проверяет права администратора."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception as e:
        log_message(f"Не удалось проверить права администратора: {e}", 'error')
        return False

def calculate_sha256(filepath):
    """Вычисляет SHA256 хеш файла."""
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

def load_local_hashes():
    """Загружает локально сохраненные хеши."""
    if os.path.exists(LOCAL_HASH_FILE):
        try:
            with open(LOCAL_HASH_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log_message(f"Ошибка загрузки локального файла хешей {LOCAL_HASH_FILE}: {e}", 'warning')
    return {}

def save_local_hashes(data):
    """Сохраняет хеши в локальный файл."""
    try:
        with open(LOCAL_HASH_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        log_message(f"Ошибка сохранения локального файла хешей {LOCAL_HASH_FILE}: {e}", 'error')

def update_local_hashes_for_version(installed_dir, version):
    """Вычисляет и сохраняет хеши для ключевых файлов указанной версии."""
    log_message(f"Вычисление и сохранение хешей для версии {version}...")
    all_local_hashes = load_local_hashes()
    current_version_hashes = {}
    success = True
    for relative_path in KEY_FILES_TO_HASH:
        file_path = os.path.join(installed_dir, relative_path.replace('/', os.sep))
        file_hash = calculate_sha256(file_path)
        if file_hash:
            current_version_hashes[relative_path] = file_hash
        else:
            log_message(f"Не удалось вычислить хеш для {relative_path} (возможно, файл отсутствует?).", "warning")
            success = False # Хеши будут неполными
    all_local_hashes[version] = current_version_hashes
    save_local_hashes(all_local_hashes)
    if success: log_message(f"Локальные хеши для версии {version} обновлены.")
    return success

def verify_local_installation_with_saved_hashes(installed_dir, installed_version):
    """Проверяет локальную установку по сохраненным хешам."""
    all_local_hashes = load_local_hashes()
    expected_hashes = all_local_hashes.get(installed_version)
    if not expected_hashes:
        log_message(f"Нет сохраненных хешей для проверки версии {installed_version}. Проверка целостности пропускается.", "warning")
        return True # Считаем консистентной, если не можем проверить
    log_message(f"Проверка целостности локальной установки версии {installed_version} по сохраненным хешам...")
    consistent = True
    for relative_path, expected_hash in expected_hashes.items():
        file_path = os.path.join(installed_dir, relative_path.replace('/', os.sep))
        actual_hash = calculate_sha256(file_path)
        if not actual_hash:
            log_message(f"Файл {relative_path} не найден локально, хотя хеш для него сохранен.", "warning")
            consistent = False
            continue
        if actual_hash.lower() != expected_hash.lower():
            log_message(f"Хеш {relative_path}: ОШИБКА! Ожидался (сохраненный): {expected_hash[:8]}..., Реальный: {actual_hash[:8]}...", "error")
            consistent = False
    if consistent: log_message("Проверка целостности локальной установки: OK", "info")
    else: log_message("Проверка целостности локальной установки: ОБНАРУЖЕНЫ НЕСООТВЕТСТВИЯ!", "warning")
    return consistent

def read_version_file(version_file_path):
    """Читает данные из version.txt."""
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
    """Получает текущую версию из version.txt."""
    version_file = os.path.join(installed_dir, 'version.txt')
    version_data = read_version_file(version_file)
    return version_data.get('ver')

def get_latest_version():
    """Получает номер последней версии с GitHub."""
    log_message("Запрашиваю информацию о последней версии с GitHub...")
    g = Github() # Без токена - ограниченное число запросов
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
    """Получает список дисков."""
    import string
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]

def is_valid_installation(path):
    """Проверяет, является ли путь корректной установкой Zapret."""
    if not os.path.isdir(path): return False
    try: # Проверка на временные папки
        temp_paths = [os.path.realpath(os.getenv(var)) for var in ['TEMP', 'TMP'] if os.getenv(var)]
        if any(os.path.realpath(path).startswith(temp) for temp in temp_paths if temp): return False
    except Exception: pass # Игнорируем ошибки проверки временных папок

    try: # Проверка наличия файлов
        found_files = set(os.listdir(path))
        bin_path = os.path.join(path, 'bin')
        if os.path.isdir(bin_path): found_files.update(['bin/' + f for f in os.listdir(bin_path)])
        matched_files = SIGNATURE_FILES.intersection(found_files)
        # Проверяем и количество, и наличие ключевых батников
        return len(matched_files) >= MIN_SIGNATURE_MATCH and {'service_remove.bat', 'service_install.bat'}.issubset(found_files)
    except Exception: return False # Ошибка чтения папки и т.д.


def search_installation():
    """Ищет установленную версию."""
    log_message("Ищу существующую установку Zapret...")
    # Проверка стандартных путей
    program_files = os.getenv('ProgramFiles')
    program_files_x86 = os.getenv('ProgramFiles(x86)')
    common_paths = []

    # Добавляем Program Files в список для проверки
    if program_files:
        common_paths.append(program_files)

    # Добавляем Program Files (x86), если он существует и отличается от Program Files
    # --- ИСПРАВЛЕННАЯ СТРОКА ---
    if program_files_x86 and program_files_x86 != program_files:
        common_paths.append(program_files_x86)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---


    for common_path in common_paths:
        log_message(f"Проверяю стандартную папку: {common_path}", 'debug')
        try:
            for entry in os.scandir(common_path):
                 # Ищем папки, содержащие 'zapret' в имени (регистронезависимо)
                 if entry.is_dir(follow_symlinks=False) and 'zapret' in entry.name.lower():
                     if is_valid_installation(entry.path):
                         log_message(f"Найдена установка в стандартной папке: {entry.path}")
                         return entry.path
        except OSError as e:
             log_message(f"Ошибка доступа к {common_path}: {e}", 'warning')
    # Полный поиск по дискам, если не нашли
    log_message("Поиск в стандартных папках не дал результатов. Начинаю поиск по всем дискам (это может занять время)...", 'info')
    for drive in get_drives():
        log_message(f"Проверяю диск {drive}...", 'debug')
        try:
            for root, dirs, files in os.walk(drive, topdown=True):
                # Оптимизация: пропускаем системные и большие папки
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in ['windows', '$recycle.bin', 'system volume information', 'programdata', 'appdata', 'recovery', 'config.msi', 'games', 'steam', 'users']]
                # Проверяем, если имя папки похоже на zapret
                if 'zapret' in os.path.basename(root).lower():
                    if is_valid_installation(root):
                        log_message(f"Найдена установка: {root}")
                        return root
        except Exception: pass # Игнорируем ошибки доступа при сканировании
    log_message("Существующая установка Zapret не найдена.", 'warning')
    return None

def ask_for_installation_path(title="Выберите папку для установки Zapret"):
    """Запрашивает путь для установки/обновления."""
    log_message(f"Пожалуйста, выберите папку в появившемся окне.")
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    # Предлагаем начальную директорию (Program Files или диск C:)
    initial_dir = os.getenv('ProgramFiles', 'C:\\')
    path = filedialog.askdirectory(title=title, initialdir=initial_dir)
    root.destroy()
    if path:
        log_message(f"Выбрана папка: {path}")
        # Проверим, можно ли в нее писать (простая проверка)
        try:
             test_file = os.path.join(path, "test_write.tmp")
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

def run_as_admin(bat_file):
    """Запускает .bat от имени администратора."""
    if not os.path.exists(bat_file):
        log_message(f"Ошибка: Файл {bat_file} не найден.", 'error')
        return False
    log_message(f"Запускаю {os.path.basename(bat_file)} от имени администратора (может потребоваться подтверждение UAC)...", 'info')
    try:
        command = f'powershell Start-Process cmd -ArgumentList "/c \"\"\"{bat_file}\"\"\"" -Verb RunAs -Wait -WindowStyle Hidden'
        result = subprocess.run(command, shell=True, check=False, capture_output=True, text=True, encoding='cp866', errors='ignore', timeout=120)
        if result.returncode == 0:
            log_message(f"{os.path.basename(bat_file)} успешно выполнен.", 'info')
            return True
        elif result.returncode == 1223: # ERROR_CANCELLED by UAC
             log_message(f"Запуск {os.path.basename(bat_file)} отменен пользователем (UAC).", 'error')
             return False
        else:
            log_message(f"Ошибка при выполнении {os.path.basename(bat_file)} (код: {result.returncode}).", 'error')
            if result.stderr: log_message(f"Вывод ошибки:\n{result.stderr.strip()}", 'error')
            return False
    except subprocess.TimeoutExpired:
        log_message(f"Время ожидания выполнения {os.path.basename(bat_file)} истекло.", 'error')
        return False
    except Exception as e:
        log_message(f"Неожиданная ошибка при запуске {bat_file}: {e}", 'error')
        return False

def kill_processes_using_folder(folder_path):
    """Завершает процессы, использующие папку."""
    killed_count = 0
    folder_realpath = os.path.realpath(folder_path)
    for proc in psutil.process_iter(['pid', 'name', 'open_files', 'exe']):
        try:
            exe_path = proc.info.get('exe')
            if exe_path and os.path.realpath(exe_path).startswith(folder_realpath):
                 log_message(f"Обнаружен процесс {proc.info['name']} (PID: {proc.info['pid']}), запущенный из {folder_realpath}. Завершаю...", 'warning')
                 proc.kill()
                 killed_count += 1
                 time.sleep(0.5)
                 continue
            open_files = proc.info.get('open_files')
            if open_files:
                for file_handle in open_files:
                    try:
                        if os.path.realpath(file_handle.path).startswith(folder_realpath):
                            log_message(f"Обнаружен процесс {proc.info['name']} (PID: {proc.info['pid']}), использующий файл в {folder_realpath}. Завершаю...", 'warning')
                            proc.kill()
                            killed_count += 1
                            time.sleep(0.5)
                            break
                    except Exception: pass # Игнорируем ошибки проверки пути
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess): continue
        except Exception as e: log_message(f"Ошибка при проверке процесса {proc.info.get('name', '?')} (PID: {proc.pid}): {e}", 'error')
    if killed_count > 0: log_message(f"Завершено процессов: {killed_count}.", 'info')

def safe_remove_folder(folder_path, retries=5, delay=2):
    """Безопасное удаление папки."""
    if not os.path.exists(folder_path): return True
    log_message(f"Попытка удаления папки: {folder_path}...")
    for attempt in range(retries):
        try: kill_processes_using_folder(folder_path)
        except Exception as e: log_message(f"Ошибка при завершении процессов перед удалением: {e}", "warning")
        try:
            shutil.rmtree(folder_path)
            time.sleep(0.5)
            if not os.path.exists(folder_path):
                log_message(f"Папка успешно удалена.")
                return True
        except Exception as e:
             log_message(f"Ошибка удаления (попытка {attempt + 1}/{retries}): {e}", 'warning')
        if attempt < retries - 1: time.sleep(delay)
    log_message(f"Не удалось удалить папку {folder_path} после {retries} попыток.", 'error')
    return False

def download_release_zip(version_to_download, target_zip_path):
    """Скачивает ZIP-архив указанной версии."""
    zip_filename = f"zapret-discord-youtube-{version_to_download}.zip"
    urls_to_try = [ # Пробуем URL с 'v' и без
        f"https://github.com/{REPO_NAME}/releases/download/v{version_to_download}/{zip_filename}",
        f"https://github.com/{REPO_NAME}/releases/download/{version_to_download}/{zip_filename}"
    ]
    for url in urls_to_try:
        log_message(f"Пытаюсь скачать с URL: {url}")
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, stream=True, timeout=60)
                response.raise_for_status()
                with open(target_zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
                dl_size_mb = os.path.getsize(target_zip_path)/1024/1024
                if dl_size_mb > 0.1:
                    log_message(f"Архив версии {version_to_download} успешно скачан ({dl_size_mb:.2f} MB).")
                    return True
                else: # Файл скачался, но слишком маленький
                     log_message("Размер скачанного файла подозрительно мал. Попытка не удалась.", "warning")
                     if os.path.exists(target_zip_path): os.remove(target_zip_path)
                     continue # К следующей попытке (если есть)
            except requests.exceptions.HTTPError as e:
                 if e.response.status_code == 404: break # 404 - нет смысла повторять этот URL
                 log_message(f"HTTP ошибка (попытка {attempt + 1}): {e}", 'error')
            except requests.exceptions.RequestException as e:
                log_message(f"Сетевая ошибка (попытка {attempt + 1}): {e}", 'error')
            if attempt < MAX_RETRIES - 1: time.sleep(RETRY_DELAY)
    log_message(f"Не удалось скачать архив версии {version_to_download}.", 'error')
    return False

def unpack_zip(zip_path, target_dir):
    """Распаковывает ZIP архив."""
    log_message(f"Распаковка архива {os.path.basename(zip_path)} в {target_dir}...")
    try:
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)
        log_message("Архив успешно распакован.")
        return True
    except zipfile.BadZipFile:
        log_message(f"Ошибка: Файл {zip_path} поврежден или не является ZIP-архивом.", 'error')
        return False
    except Exception as e:
        log_message(f"Критическая ошибка при распаковке архива: {e}", 'error')
        return False

def create_desktop_shortcut(install_dir):
    """Создает ярлык на рабочий стол для general.bat."""
    target_bat_path = os.path.join(install_dir, SHORTCUT_TARGET_BAT)
    if not os.path.exists(target_bat_path):
        log_message(f"Не найден файл {SHORTCUT_TARGET_BAT} для создания ярлыка.", "warning")
        return False

    try:
        desktop_path = winshell.desktop()
        shortcut_path = os.path.join(desktop_path, SHORTCUT_NAME)
        log_message(f"Создание/обновление ярлыка на рабочем столе: {shortcut_path}")

        # Используем winshell для создания ярлыка
        with winshell.shortcut(shortcut_path) as shortcut:
            shortcut.path = target_bat_path          # Целевой файл
            shortcut.working_directory = install_dir # Рабочая папка
            shortcut.description = "Запустить Zapret (обход блокировок)"
            # shortcut.icon_location = (os.path.join(install_dir, "bin", "some_icon.ico"), 0) # Пример иконки
            shortcut.run_as_admin = True             # <--- Запуск от имени администратора

        log_message("Ярлык на рабочем столе успешно создан/обновлен.", "info")
        return True
    except Exception as e:
        log_message(f"Не удалось создать ярлык на рабочем столе: {e}", "error")
        return False

def perform_initial_install(latest_version, install_dir):
    """Выполняет первую установку."""
    log_message(f"Начинаю установку Zapret версии {latest_version} в папку: {install_dir}")
    temp_base_path = os.getenv('TEMP', '.')
    temp_path = os.path.join(temp_base_path, TEMP_SUBDIR)
    os.makedirs(temp_path, exist_ok=True)
    zip_path = os.path.join(temp_path, f"zapret-install-{latest_version}.zip")

    # 1. Скачать архив
    if not download_release_zip(latest_version, zip_path):
        if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)
        return False # Ошибка уже залогирована

    # 2. Распаковать архив
    if not unpack_zip(zip_path, install_dir):
        if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)
        # Попытаться удалить частично распакованные файлы?
        safe_remove_folder(install_dir)
        return False # Ошибка уже залогирована

    # 3. Обновить локальные хеши
    update_local_hashes_for_version(install_dir, latest_version)

    # 4. Создать ярлык
    create_desktop_shortcut(install_dir)

    # 5. Очистить временные файлы
    log_message("Очистка временных файлов установки...")
    if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)

    log_message("-" * 30)
    log_message(f"УСПЕХ! Zapret версии {latest_version} успешно установлен в '{install_dir}'.")
    log_message(f"На вашем рабочем столе создан ярлык '{SHORTCUT_NAME}'.")
    log_message("Вы можете запустить его для обхода блокировок.")
    log_message("Для настройки автозапуска используйте service_install.bat (от им. Администратора).")
    log_message("-" * 30)
    return True


def perform_update(latest_version, installed_dir):
    """Выполняет обновление существующей установки."""
    log_message(f"Начинаю обновление Zapret до версии {latest_version} в папке: {installed_dir}")
    temp_base_path = os.getenv('TEMP', '.')
    temp_path = os.path.join(temp_base_path, TEMP_SUBDIR)
    os.makedirs(temp_path, exist_ok=True)
    zip_path = os.path.join(temp_path, f"zapret-update-{latest_version}.zip")

    # 1. Скачать архив
    if not download_release_zip(latest_version, zip_path):
        if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)
        return False

    # 2. Остановить службы и процессы
    service_remove_bat = os.path.join(installed_dir, 'service_remove.bat')
    if os.path.exists(service_remove_bat): run_as_admin(service_remove_bat)
    else: log_message("Файл service_remove.bat не найден, службы не остановлены.", 'warning')
    log_message("Пытаюсь завершить процессы, использующие папку установки...")
    kill_processes_using_folder(installed_dir)

    # 3. Удалить старую версию
    log_message("Удаляю старую версию...")
    if not safe_remove_folder(installed_dir):
        log_message("Критическая ошибка: Не удалось удалить старую версию.", 'error')
        if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)
        return False

    # 4. Распаковать новую версию
    if not unpack_zip(zip_path, installed_dir):
        if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)
        log_message("Критическая ошибка: Не удалось распаковать новую версию. Папка установки может быть пуста.", 'error')
        return False

    # 5. Обновить локальные хеши
    update_local_hashes_for_version(installed_dir, latest_version)

    # 6. Создать/обновить ярлык
    create_desktop_shortcut(installed_dir)

    # 7. Очистить временные файлы
    log_message("Очистка временных файлов обновления...")
    if os.path.exists(temp_path): shutil.rmtree(temp_path, ignore_errors=True)

    log_message("-" * 30)
    log_message(f"УСПЕХ! Zapret успешно обновлен до версии {latest_version} в '{installed_dir}'.")
    log_message(f"Ярлык '{SHORTCUT_NAME}' на рабочем столе обновлен (если был).")
    log_message("Если вы использовали службу автозапуска, ее нужно переустановить (service_install.bat).")
    log_message("-" * 30)
    return True


# --- Основная логика ---
def run_main_logic():
    """Основной поток выполнения скрипта."""
    log_message("-" * 50)
    log_message("Запуск установщика/обновления Zapret для Discord/YouTube")
    log_message("Автор скрипта: на основе работы сообщества и Flowseal")
    log_message("Версия скрипта: 2.0 (с установкой и ярлыком)")
    log_message(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_message("-" * 50)

    # Проверка прав (хотя UAC должен был отработать)
    if not is_admin():
         log_message("Критическая ошибка: Скрипт запущен без прав Администратора!", "critical")
         log_message("Пожалуйста, перезапустите скрипт с правами Администратора.", "critical")
         return # Выход без input(), т.к. это внутренняя ошибка

    # 1. Поиск существующей установки
    installed_dir = search_installation()
    installation_found = installed_dir is not None

    # 2. Получение последней версии с GitHub
    latest_version = get_latest_version()
    if not latest_version:
        log_message("Не удалось получить информацию о последней версии с GitHub.", 'error')
        log_message("Проверьте интернет-соединение и доступность GitHub.", 'error')
        return # Выход, т.к. без версии нельзя ни установить, ни обновить

    # 3. Логика действий: Установка или Обновление?
    if not installation_found:
        # --- Сценарий Первой Установки ---
        log_message("Программа Zapret не найдена на этом компьютере.")
        if ask_for_user_confirmation("Хотите установить последнюю версию сейчас?"):
            chosen_path = ask_for_installation_path(title="Выберите папку для НОВОЙ установки Zapret")
            if chosen_path:
                # Проверим, не существует ли там уже что-то похожее на zapret
                if os.path.exists(os.path.join(chosen_path, "version.txt")):
                     if not ask_for_user_confirmation(f"В папке '{chosen_path}' уже есть файлы Zapret. Перезаписать?"):
                         log_message("Установка отменена пользователем.")
                         return
                     else: # Пользователь согласился перезаписать
                         if not safe_remove_folder(chosen_path):
                              log_message("Не удалось очистить папку перед установкой.", "error")
                              return
                # Выполняем установку
                perform_initial_install(latest_version, chosen_path)
            else:
                log_message("Папка для установки не выбрана. Установка отменена.")
        else:
            log_message("Установка отменена пользователем.")
    else:
        # --- Сценарий Обновления ---
        log_message(f"Обнаружена существующая установка Zapret в папке: {installed_dir}")
        current_version = get_current_version(installed_dir)

        if not current_version:
            log_message("Не удалось определить версию установленной программы (файл version.txt поврежден или отсутствует).", "warning")
            local_consistency = False # Считаем неконсистентной
        else:
            log_message(f"Установленная версия: {current_version}")
            local_consistency = verify_local_installation_with_saved_hashes(installed_dir, current_version)

        # Сравнение версий
        update_needed = False
        reason = ""
        if not current_version:
             update_needed = True
             reason = "текущая версия не определена"
        elif not local_consistency:
             update_needed = True
             reason = "проверка целостности файлов не пройдена"
        elif latest_version != current_version:
             try:
                 if pkg_version.parse(latest_version) > pkg_version.parse(current_version):
                     update_needed = True
                     reason = f"доступна новая версия {latest_version}"
                 else:
                     reason = f"установлена последняя или более новая версия ({current_version})"
             except Exception as e:
                 log_message(f"Ошибка сравнения версий: {e}. Считаем, что обновление нужно.", "warning")
                 update_needed = True # Обновляем на всякий случай
                 reason = "ошибка сравнения версий"
        else:
            reason = f"установлена последняя версия ({current_version}) и проверка файлов пройдена"

        log_message(f"Результат проверки: {reason}.")

        if update_needed:
            if ask_for_user_confirmation(f"Обнаружена причина для обновления ({reason}). Начать обновление до версии {latest_version}?"):
                perform_update(latest_version, installed_dir)
            else:
                log_message("Обновление отменено пользователем.")
        else:
            log_message("Обновление не требуется.")


# --- ТОЧКА ВХОДА И ЗАПРОС ПРАВ АДМИНИСТРАТОРА ---
if __name__ == "__main__":
    # Проверяем, запущен ли скрипт уже с повышенными правами (через флаг или изначально)
    if '--elevated' in sys.argv or is_admin():
        if '--elevated' in sys.argv:
             sys.argv.remove('--elevated')
             log_message("Скрипт перезапущен с правами администратора.", 'info')
        else:
             log_message("Скрипт уже запущен с правами администратора.", 'info')

        # Выполняем основную логику
        try:
            run_main_logic()
        except Exception as e:
            log_message("Произошла критическая непредвиденная ошибка:", 'critical')
            logger.exception(e) # Логируем полный traceback
            print("\nПроизошла критическая ошибка. Подробности в лог-файле.")

        # --- Запрос на закрытие окна ---
        input("\nНажмите Enter для завершения работы...")

    # Если прав нет, пытаемся перезапустить себя с запросом UAC
    else:
        log_message("Для установки и обновления требуются права Администратора.", 'warning')
        log_message("Сейчас будет запрошено разрешение на повышение прав (UAC).", 'info')
        time.sleep(2) # Даем пользователю прочитать

        script_path = os.path.abspath(sys.argv[0])
        params = ['--elevated'] + sys.argv[1:]
        params_string = subprocess.list2cmdline(params)

        try:
            # Запускаем себя же (python.exe или скомпилированный .exe) с параметром --elevated
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,           # hwnd
                "runas",        # Operation: запросить повышение прав
                sys.executable, # File: текущий исполняемый файл (python или exe)
                f'"{script_path}" {params_string}', # Parameters: путь к скрипту/exe + доп. параметры
                None,           # Directory
                1               # ShowCmd: SW_SHOWNORMAL
            )

            # Анализируем результат ShellExecuteW
            # Значения > 32 обычно означают успех (запущен новый процесс)
            if ret <= 32:
                error_codes = {
                    0: "Оперативная память или ресурсы были недостаточны.",
                    2: "Файл не найден.",
                    3: "Путь не найден.",
                    5: "Отказано в доступе (возможно, UAC отключен или заблокирован политикой).",
                    8: "Недостаточно памяти.",
                    11: "Неверный формат .exe файла.",
                    27: "Диск переполнен.",
                    31: "Не подключено устройство или не найдено приложение для файла.",
                    1155: "Нет приложения, связанного с этим типом файла (NO_ASSOCIATION).",
                    1203: "Сеть не найдена (NO_NET_OR_BAD_PATH).",
                    1223: "Операция была отменена пользователем (ERROR_CANCELLED)." # Самая частая ошибка - отказ в UAC
                }
                error_message = error_codes.get(ret, f"Неизвестная ошибка ShellExecuteW (код {ret})")
                log_message(f"Не удалось запустить процесс с повышенными правами: {error_message}", 'error')
                if ret == 1223:
                    print("\nВы отменили запрос на права Администратора.")
                elif ret == 5:
                     print("\nОтказано в доступе. Возможно, UAC отключен или заблокирован системным администратором.")
                else:
                    print(f"\nНе удалось получить права Администратора (код {ret}).")
                print("Пожалуйста, запустите скрипт вручную 'От имени администратора'.")
                input("Нажмите Enter для выхода...")
            else:
                # Успешный запуск нового процесса, старый завершаем
                log_message("Запрос на повышение прав отправлен. Исходный процесс завершается...", 'info')
                sys.exit(0)

        except Exception as e:
            log_message(f"Произошло исключение при попытке перезапуска с повышением прав: {e}", 'critical')
            logger.exception(e)
            print("\nПроизошла ошибка при попытке запросить права Администратора.")
            input("Нажмите Enter для выхода...")
            sys.exit(1)