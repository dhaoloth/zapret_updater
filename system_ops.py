import ctypes
import subprocess
import psutil
import winreg
import time
import os

from logger_setup import log_message
import config

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
            command_args, check=False, capture_output=True, text=True,
            encoding='cp866', errors='ignore', timeout=60, shell=True
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

    for service_name in config.SERVICES_TO_MANAGE:
        log_message(f"Останавливаю службу {service_name}...", 'debug')
        return_code, _, stderr = run_system_command(["net", "stop", service_name], f"Остановка {service_name}")
        if return_code != 0 and return_code != 2 and "не запущена" not in (stderr or "").lower() and "not started" not in (stderr or "").lower():
            log_message(f"Не удалось остановить службу {service_name} (код: {return_code}).", 'warning')

        log_message(f"Удаляю службу {service_name}...", 'debug')
        return_code, _, stderr = run_system_command(["sc", "delete", service_name], f"Удаление {service_name}")
        if return_code != 0 and return_code != 1060 and "не существует" not in (stderr or "").lower() and "does not exist" not in (stderr or "").lower():
            log_message(f"Не удалось удалить службу {service_name} (код: {return_code}).", 'error')
            success = False

    if success:
        log_message("Завершено управление службами.", 'info')
    else:
        log_message("При управлении службами возникли ошибки.", 'warning')
    time.sleep(1)
    return success

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
            exe_path = proc_info.get('exe')
            if exe_path and os.path.realpath(exe_path).startswith(folder_realpath):
                 log_message(f"Обнаружен процесс {proc_info['name']} (PID: {proc_info['pid']}), запущенный из {folder_realpath}. Завершаю...", 'warning')
                 proc.kill()
                 killed_count += 1
                 time.sleep(0.5)
                 continue

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
                    except Exception: pass
                if proc.is_running():
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

def save_cached_path(path):
    if not is_admin(): return
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, config.REGISTRY_KEY_PATH)
        winreg.SetValueEx(key, config.REGISTRY_VALUE_PATH, 0, winreg.REG_SZ, path)
        winreg.CloseKey(key)
        log_message(f"Путь установки сохранен в реестре: {path}", 'debug')
    except Exception as e:
        log_message(f"Не удалось сохранить путь в реестр: {e}", 'warning')

def load_cached_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, config.REGISTRY_KEY_PATH, 0, winreg.KEY_READ)
        value, reg_type = winreg.QueryValueEx(key, config.REGISTRY_VALUE_PATH)
        winreg.CloseKey(key)
        if reg_type == winreg.REG_SZ and value:
            log_message(f"Найден кешированный путь в реестре: {value}", 'debug')
            return value
        else:
             log_message("Кешированный путь в реестре имеет неверный тип или пуст.", 'warning')
             clear_updater_cache()
             return None
    except FileNotFoundError:
        log_message("Ключ реестра или значение для кешированного пути не найдено.", 'debug')
        return None
    except Exception as e:
        log_message(f"Не удалось прочитать путь из реестра: {e}", 'warning')
        return None

def save_cached_version(version_str):
    if not is_admin(): return
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, config.REGISTRY_KEY_PATH)
        winreg.SetValueEx(key, config.REGISTRY_VALUE_VERSION, 0, winreg.REG_SZ, version_str)
        winreg.CloseKey(key)
        log_message(f"Версия установки сохранена в реестре: {version_str}", 'debug')
    except Exception as e:
        log_message(f"Не удалось сохранить версию в реестр: {e}", 'warning')

def load_cached_version():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, config.REGISTRY_KEY_PATH, 0, winreg.KEY_READ)
        value, reg_type = winreg.QueryValueEx(key, config.REGISTRY_VALUE_VERSION)
        winreg.CloseKey(key)
        if reg_type == winreg.REG_SZ and value:
            log_message(f"Найдена кешированная версия в реестре: {value}", 'debug')
            return value
        else:
            log_message("Кешированная версия в реестре имеет неверный тип или пуста.", 'warning')
            clear_updater_cache()
            return None
    except FileNotFoundError:
        log_message("Ключ реестра или значение для кешированной версии не найдено.", 'debug')
        return None
    except Exception as e:
        log_message(f"Не удалось прочитать версию из реестра: {e}", 'warning')
        return None

def clear_updater_cache():
    if not is_admin(): return
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, config.REGISTRY_KEY_PATH, 0, winreg.KEY_WRITE)
        try:
            winreg.DeleteValue(key, config.REGISTRY_VALUE_PATH)
            log_message("Кешированный путь удален из реестра.", 'debug')
        except FileNotFoundError: pass
        except Exception as e_path: log_message(f"Не удалось удалить значение пути из реестра: {e_path}", 'warning')

        try:
            winreg.DeleteValue(key, config.REGISTRY_VALUE_VERSION)
            log_message("Кешированная версия удалена из реестра.", 'debug')
        except FileNotFoundError: pass
        except Exception as e_ver: log_message(f"Не удалось удалить значение версии из реестра: {e_ver}", 'warning')

        winreg.CloseKey(key)

        # Попытка удалить сам ключ, если он пуст
        try:
            parent_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software", 0, winreg.KEY_WRITE)
            winreg.DeleteKey(parent_key, "ZapretUpdater")
            winreg.CloseKey(parent_key)
            log_message("Ключ реестра ZapretUpdater удален.", 'debug')
        except FileNotFoundError: pass
        except Exception: pass

    except FileNotFoundError:
        log_message("Ключ реестра ZapretUpdater не найден.", 'debug')
    except Exception as e:
        log_message(f"Не удалось очистить кеш в реестре: {e}", 'warning')