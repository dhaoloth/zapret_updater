import os
import re
import requests
import shutil
import zipfile
import time
import logging
import subprocess
import psutil
from github import Github
from github.GithubException import RateLimitExceededException, GithubException
import tkinter as tk
from tkinter import filedialog

# Настройка логирования
LOG_FILE = 'update_zapret.log'
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# Конфигурация
REPO_NAME = "Flowseal/zapret-discord-youtube"
TEMP_PATH = os.path.join(os.getenv('TEMP'), 'zapret-temp')
SIGNATURE_FILES = {
    'version.txt',
    'service_remove.bat',
    'service_install.bat',
    'service_status.bat',
    'check_updates.bat',
    'discord.bat',
    'general.bat',
    'ipset-discord.bat',
    'list-discord.bat',
    'list-general.bat',
    'README.md'
}
MAX_RETRIES = 3
RETRY_DELAY = 5

def log_and_print(message, level='info'):
    """Выводит сообщение в консоль и логирует."""
    print(message)
    if hasattr(logging, level):
        getattr(logging, level)(message)
    else:
        logging.info(message)  # Фолбэк на info

def get_drives():
    """Получает список доступных дисков."""
    try:
        drives = [d for d in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if os.path.exists(f"{d}:\\")]
        log_and_print(f"Доступные диски: {drives}")
        return drives
    except Exception as e:
        log_and_print(f"Ошибка при получении списка дисков: {e}", 'error')
        return []

def is_valid_installation(path):
    """Проверяет, является ли путь корректной установкой программы."""
    # Исключаем временные папки
    temp_paths = [os.getenv('TEMP'), os.getenv('TMP')]
    if any(path.startswith(temp) for temp in temp_paths if temp):
        log_and_print(f"Исключена временная папка: {path}", 'debug')
        return False

    # Проверяем наличие ключевых файлов
    required_files = {'version.txt', 'service_remove.bat', 'service_install.bat'}
    found_files = set(os.listdir(path))
    if required_files.issubset(found_files):
        return True

    log_and_print(f"Недостаточно ключевых файлов в {path}", 'debug')
    return False

def search_installation():
    """Ищет установленную версию по имени папки или сигнатурным файлам."""
    log_and_print("Поиск установленной версии...")
    for drive in get_drives():
        root_path = f"{drive}:\\"
        log_and_print(f"Проверка диска {root_path}", 'debug')
        try:
            for root, dirs, files in os.walk(root_path):
                if len(SIGNATURE_FILES.intersection(set(files))) >= 3:
                    if is_valid_installation(root):
                        log_and_print(f"Найдено: {root}")
                        return root
                    else:
                        log_and_print(f"Исключена некорректная установка: {root}", 'debug')
        except Exception as e:
            log_and_print(f"Ошибка при проверке {root_path}: {e}", 'error')
    log_and_print("Установленная версия не найдена", 'warning')
    return None

def ask_for_installation_path():
    """Запрашивает путь к установке через диалоговое окно."""
    root = tk.Tk()
    root.withdraw()  # Скрываем основное окно tkinter
    path = filedialog.askdirectory(title="Укажите путь к установленной программе")
    return path

def get_current_version(installed_dir):
    """Читает текущую версию из version.txt."""
    log_and_print(f"Проверка версии в {installed_dir}")
    try:
        with open(os.path.join(installed_dir, 'version.txt'), 'r', encoding='utf-8') as f:
            version = re.search(r'\d+\.\d+\.\d+', f.read())
            if version:
                log_and_print(f"Текущая версия: {version.group()}")
                return version.group()
    except Exception as e:
        log_and_print(f"Ошибка чтения version.txt: {e}", 'error')
    return None

def get_latest_version():
    """Получает последнюю версию с GitHub."""
    log_and_print("Запрос версии с GitHub")
    g = Github()
    retries = MAX_RETRIES

    for attempt in range(retries):
        try:
            repo = g.get_repo(REPO_NAME)
            latest_release = repo.get_latest_release()
            version = latest_release.tag_name.lstrip('v')
            log_and_print(f"Последняя версия: {version}")
            return version
        except RateLimitExceededException:
            log_and_print(f"Превышен лимит запросов к GitHub API. Попытка {attempt + 1} из {retries}", 'error')
        except GithubException as e:
            log_and_print(f"Ошибка GitHub API: {e}. Попытка {attempt + 1} из {retries}", 'error')
        
        time.sleep(RETRY_DELAY)
    
    log_and_print("Не удалось получить последнюю версию", 'error')
    return None

def run_as_admin(bat_file):
    """Запускает .bat файл от имени администратора."""
    try:
        # Используем PowerShell для запуска от имени администратора
        command = f'powershell Start-Process "{bat_file}" -Verb RunAs'
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        log_and_print(f"Команда выполнена: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        log_and_print(f"Ошибка при запуске {bat_file}: {e.stderr}", 'error')
        return False

def kill_processes_using_folder(folder_path):
    """Завершает процессы, использующие файлы в указанной папке."""
    for proc in psutil.process_iter(['pid', 'name', 'open_files']):
        try:
            for file in proc.info['open_files'] or []:
                if file.path.startswith(folder_path):
                    log_and_print(f"Завершение процесса {proc.info['name']} (PID: {proc.info['pid']})", 'warning')
                    proc.kill()
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

def safe_remove_folder(folder_path, retries=5, delay=2):
    """Безопасное удаление папки с повторными попытками."""
    for attempt in range(retries):
        try:
            kill_processes_using_folder(folder_path)  # Завершаем процессы перед удалением
            shutil.rmtree(folder_path)
            log_and_print(f"Папка {folder_path} успешно удалена")
            return True
        except Exception as e:
            log_and_print(f"Ошибка удаления папки (попытка {attempt + 1}/{retries}): {e}", 'warning')
            time.sleep(delay)
    log_and_print(f"Не удалось удалить папку {folder_path}", 'error')
    return False

def download_and_update(latest_version, installed_dir):
    """Скачивает и обновляет программу."""
    log_and_print(f"Обновление до {latest_version}")
    zip_path = os.path.join(TEMP_PATH, f"zapret-{latest_version}.zip")
    os.makedirs(TEMP_PATH, exist_ok=True)

    # Формируем правильный URL для загрузки
    url = f"https://github.com/{REPO_NAME}/releases/download/{latest_version}/zapret-{latest_version}.zip"
    log_and_print(f"Используемый URL для загрузки: {url}")

    retries = MAX_RETRIES

    for attempt in range(retries):
        try:
            response = requests.get(url, stream=True, timeout=10)
            response.raise_for_status()
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)
            
            log_and_print(f"Скачано в {zip_path}")
            break  # Если скачивание успешно, выходим из цикла
        except requests.RequestException as e:
            log_and_print(f"Ошибка загрузки (попытка {attempt + 1}/{retries}): {e}", 'error')
            time.sleep(RETRY_DELAY)
    else:
        log_and_print("Не удалось скачать обновление", 'error')
        return

    # Остановка служб и процессов через service_remove.bat
    service_remove_bat = os.path.join(installed_dir, 'service_remove.bat')
    if os.path.exists(service_remove_bat):
        log_and_print("Остановка служб и процессов...")
        if not run_as_admin(service_remove_bat):
            log_and_print("Не удалось остановить службы и процессы через service_remove.bat", 'error')
    else:
        log_and_print("Файл service_remove.bat не найден", 'warning')

    # Принудительное завершение процессов, использующих файлы в папке bin
    bin_folder = os.path.join(installed_dir, 'bin')
    if os.path.exists(bin_folder):
        log_and_print("Завершение процессов, использующих файлы в папке bin...")
        kill_processes_using_folder(bin_folder)

    # Удаляем старую версию
    if not safe_remove_folder(installed_dir):
        log_and_print("Не удалось удалить старую версию", 'error')
        return

    # Распаковываем новую версию
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(installed_dir)
        log_and_print(f"Установлено в {installed_dir}")
    except Exception as e:
        log_and_print(f"Ошибка при распаковке: {e}", 'error')
        return

    # Очищаем временные файлы
    shutil.rmtree(TEMP_PATH, ignore_errors=True)

def main():
    log_and_print("Запуск обновления")
    installed_dir = search_installation()
    if not installed_dir:
        log_and_print("Установка не найдена автоматически. Запрос пути вручную...")
        installed_dir = ask_for_installation_path()
        if not installed_dir:
            log_and_print("Путь не указан. Обновление отменено.", 'error')
            return

    current_version = get_current_version(installed_dir)
    latest_version = get_latest_version()
    if current_version and latest_version and current_version != latest_version:
        download_and_update(latest_version, installed_dir)
    else:
        log_and_print("Обновление не требуется")
    log_and_print("Завершено")

if __name__ == "__main__":
    main()
