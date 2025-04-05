import os
import sys
import subprocess
import time
import requests
from packaging import version as pkg_version

from logger_setup import log_message
import config
import github_api
import filesystem # Нужен download_file

def perform_self_update(latest_updater_release):
    log_message("Начинаю процесс самообновления...")

    if not getattr(sys, 'frozen', False):
        log_message("Самообновление возможно только для скомпилированного EXE.", "error")
        return False

    current_exe_path = sys.executable
    current_exe_name = os.path.basename(current_exe_path)
    updater_asset = None

    for asset in latest_updater_release.get_assets():
        # Ищем .exe с именем как у запущенного файла (регистронезависимо)
        if asset.name.lower() == current_exe_name.lower():
            updater_asset = asset
            break

    if not updater_asset:
        log_message(f"Не найден файл ассета '{current_exe_name}' в последнем релизе обновлятора {config.UPDATER_REPO}.", "error")
        return False

    try:
        temp_dir = os.path.dirname(current_exe_path)
        # Проверяем права на запись в папку с EXE
        if not filesystem.check_write_permission(temp_dir):
            log_message(f"Нет прав на запись в папку {temp_dir}. Самообновление невозможно.", "error")
            return False
        new_exe_temp_path = os.path.join(temp_dir, "_new_" + current_exe_name)
        bat_path = os.path.join(temp_dir, "_updater_replace.bat")
    except Exception as e:
         log_message(f"Ошибка подготовки путей для самообновления: {e}", "error")
         return False


    log_message(f"Скачиваю новую версию в {new_exe_temp_path}...")
    if not filesystem.download_file(updater_asset.browser_download_url, new_exe_temp_path, "обновлятор"):
        if os.path.exists(new_exe_temp_path): os.remove(new_exe_temp_path)
        return False

    bat_content = f"""@echo off
chcp 65001 > nul
echo Ожидание завершения старого процесса...
timeout /t 3 /nobreak > nul
echo Попытка принудительного завершения старого процесса (на всякий случай)...
taskkill /im "{current_exe_name}" /f > nul 2>&1
echo Удаление старого файла "{current_exe_name}"...
del "{current_exe_path}"
if exist "{current_exe_path}" (
    echo Не удалось удалить старый файл! Обновление прервано.
    del "{new_exe_temp_path}" > nul
    pause
    del "%~f0"
    exit /b 1
)
echo Переименование нового файла...
ren "{new_exe_temp_path}" "{current_exe_name}"
if not exist "{current_exe_path}" (
    echo Не удалось переименовать новый файл! Обновление прервано.
    pause
    del "%~f0"
    exit /b 1
)
echo Обновление завершено. Запускаю новую версию...
start "" "{current_exe_path}"
echo Удаляю временный скрипт...
del "%~f0"
exit /b 0
"""
    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)
        log_message(f"Временный BAT файл создан: {bat_path}")
    except Exception as e:
        log_message(f"Не удалось создать временный BAT файл: {e}", "error")
        if os.path.exists(new_exe_temp_path): os.remove(new_exe_temp_path)
        return False

    log_message("Запускаю BAT файл для замены EXE и завершаю текущий процесс...")
    try:
        subprocess.Popen([bat_path], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True, shell=False)
        return True # Возвращаем True, чтобы основной скрипт мог завершиться
    except Exception as e:
        log_message(f"Не удалось запустить BAT файл: {e}", "error")
        if os.path.exists(new_exe_temp_path): os.remove(new_exe_temp_path)
        if os.path.exists(bat_path): os.remove(bat_path)
        return False


def check_self_update(ask_confirmation_func):
    log_message(f"Текущая версия обновлятора: {config.UPDATER_VERSION}", "info")
    latest_updater_release = github_api.get_latest_github_release(config.UPDATER_REPO)
    if not latest_updater_release:
        log_message("Не удалось проверить обновления для самого обновлятора.", "warning")
        return False

    latest_version_str = latest_updater_release.tag_name.lstrip('v')
    log_message(f"Последняя версия обновлятора на GitHub: {latest_version_str}", "info")

    try:
        if pkg_version.parse(latest_version_str) > pkg_version.parse(config.UPDATER_VERSION):
            log_message("Доступна новая версия обновлятора!", "warning")
            print("-" * 30)
            print(f"!!! Доступно обновление для самой программы обновления Zapret !!!")
            print(f"Текущая версия: {config.UPDATER_VERSION}")
            print(f"Новая версия:   {latest_version_str}")
            print("-" * 30)
            if ask_confirmation_func("Хотите скачать и установить обновление сейчас? Программа перезапустится."):
                 if perform_self_update(latest_updater_release):
                     log_message("Процесс самообновления запущен. Текущая программа завершится.", "info")
                     return True # Возвращаем True, чтобы основной скрипт завершился
                 else:
                     log_message("Самообновление не удалось.", "error")
                     input("Нажмите Enter для продолжения со старой версией...")
                     return False # Продолжаем со старой версией
            else:
                log_message("Самообновление отклонено пользователем.", "info")
                return False # Продолжаем со старой версией
        else:
            log_message("Используется последняя версия обновлятора.", "info")
            return False # Обновление не требуется
    except Exception as e:
        log_message(f"Ошибка при сравнении версий обновлятора: {e}", "error")
        return False # Ошибка сравнения, продолжаем со старой версией