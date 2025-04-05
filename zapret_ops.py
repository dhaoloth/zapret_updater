import os
import time

from logger_setup import log_message, logger
import config
import system_ops
import filesystem
import github_api

def is_valid_installation(path):
    log_message(f"Проверка папки на валидность установки Zapret: {path}", 'debug')
    if not os.path.isdir(path): return False
    try:
        temp_paths = [os.path.realpath(os.getenv(var)) for var in ['TEMP', 'TMP'] if os.getenv(var)]
        real_path = os.path.realpath(path)
        is_temp = any(real_path.startswith(temp) for temp in temp_paths if temp)
        if is_temp: return False
    except Exception as e:
        log_message(f"Предупреждение при проверке на временную папку [{path}]: {e}", 'debug')

    bin_path = os.path.join(path, 'bin')
    if not os.path.isdir(bin_path): return False

    try:
        bin_files = set(f.lower() for f in os.listdir(bin_path) if os.path.isfile(os.path.join(bin_path, f)))
        if not config.BIN_ESSENTIAL_FILES.issubset(bin_files):
            log_message(f"Результат [{path}]: Не все ключевые файлы найдены в bin. Отсутствуют: {config.BIN_ESSENTIAL_FILES - bin_files}", 'debug')
            return False
    except Exception as e:
        log_message(f"Ошибка чтения папки 'bin' [{bin_path}]: {e}", 'warning')
        return False

    try:
        root_files = os.listdir(path)
        has_bat = any(f.lower().endswith('.bat') and os.path.isfile(os.path.join(path, f)) for f in root_files)
        has_txt = any(f.lower().endswith('.txt') and os.path.isfile(os.path.join(path, f)) for f in root_files)
        if not has_bat:
            log_message(f"Результат [{path}]: Отсутствуют .bat файлы в корневой папке", 'debug')
            return False
        if not has_txt:
            log_message(f"Результат [{path}]: Отсутствуют .txt файлы в корневой папке", 'debug')
            return False
    except Exception as e:
        log_message(f"Ошибка чтения корневой папки [{path}]: {e}", 'warning')
        return False

    log_message(f"Результат [{path}]: ВАЛИДНО", 'info')
    return True


def ask_for_manual_search_path(ask_confirmation_func):
    print("-" * 30)
    if not ask_confirmation_func("Автоматический поиск не дал результатов. Хотите указать папку вручную?"):
        log_message("Пользователь отказался указывать папку вручную.", "info")
        return None
    manual_path = filesystem.ask_for_path_dialog("Укажите папку с установленным Zapret")
    if manual_path:
        log_message(f"Проверка папки, указанной вручную: {manual_path}", "info")
        if is_valid_installation(manual_path):
             log_message(f"Установка найдена в указанной папке: {manual_path}")
             system_ops.save_cached_path(manual_path)
             # Не сохраняем версию здесь, т.к. мы не знаем ее точно
             return manual_path
        else:
            log_message(f"В указанной папке ({manual_path}) не найдена корректная установка Zapret.", "warning")
            print(f"В выбранной папке ({manual_path}) не найдена корректная установка.")
            return None
    else:
        log_message("Папка для ручной проверки не выбрана.", "warning")
        return None

def search_installation(ask_confirmation_func):
    log_message("Ищу существующую установку Zapret...")
    cached_path = system_ops.load_cached_path()
    if cached_path and os.path.isdir(cached_path):
        log_message(f"Проверяю кешированный путь: {cached_path}", 'info')
        if is_valid_installation(cached_path):
            log_message("Кешированный путь валиден.", 'info')
            return cached_path
        else:
            log_message("Кешированный путь невалиден. Очищаю кеш.", 'warning')
            system_ops.clear_updater_cache()

    program_files = os.getenv('ProgramFiles')
    program_files_x86 = os.getenv('ProgramFiles(x86)')
    common_paths_to_check = []
    if program_files: common_paths_to_check.append(program_files)
    if program_files_x86 and program_files_x86 != program_files: common_paths_to_check.append(program_files_x86)
    common_paths_to_check.append('C:\\Zapret')

    for common_path_base in common_paths_to_check:
        log_message(f"Проверяю стандартную папку/путь: {common_path_base}", 'debug')
        if os.path.isdir(common_path_base):
            if is_valid_installation(common_path_base):
                 log_message(f"Найдена установка в стандартном пути: {common_path_base}")
                 system_ops.save_cached_path(common_path_base)
                 return common_path_base
            if common_path_base == program_files or common_path_base == program_files_x86:
                try:
                    for entry in os.scandir(common_path_base):
                         if entry.is_dir(follow_symlinks=False) and 'zapret' in entry.name.lower():
                             if is_valid_installation(entry.path):
                                 log_message(f"Найдена установка в подпапке: {entry.path}")
                                 system_ops.save_cached_path(entry.path)
                                 return entry.path
                except OSError as e:
                     log_message(f"Ошибка доступа к {common_path_base}: {e}", 'warning')

    log_message("Поиск в стандартных путях не дал результатов. Начинаю поиск по дискам...", 'info')
    all_drives = filesystem.get_drives()
    if not all_drives:
        log_message("Не удалось получить список дисков.", "error")
        return ask_for_manual_search_path(ask_confirmation_func)

    found_path = None
    for drive in all_drives:
        log_message(f"Проверяю диск {drive} (глубина до {config.SEARCH_DEPTH_LIMIT})...", 'info')
        drive_root_path = drive.rstrip(os.sep)
        try:
            for root, dirs, files in os.walk(drive, topdown=True):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in config.EXCLUDED_DIRS_SEARCH]
                relative_path = os.path.relpath(root, drive_root_path)
                if relative_path == '.': current_depth = 0
                else: current_depth = relative_path.count(os.sep) + 1
                log_message(f"Скан: {root} (глубина {current_depth})", 'debug')
                if current_depth <= config.SEARCH_DEPTH_LIMIT:
                    if is_valid_installation(root):
                        log_message(f"Найдена установка (ограниченный скан): {root}")
                        system_ops.save_cached_path(root)
                        found_path = root
                        break
                if current_depth >= config.SEARCH_DEPTH_LIMIT:
                    log_message(f"Достигнут лимит глубины в {root}.", 'debug')
                    dirs[:] = []
            if found_path: break
        except Exception as e:
             log_message(f"Ошибка сканирования {drive} в {root if 'root' in locals() else ''}: {e}", 'debug')
             pass

    if found_path:
        log_message(f"Итоговый найденный путь: {found_path}")
        return found_path
    else:
        log_message("Установка не найдена при автоматическом сканировании.", 'warning')
        return ask_for_manual_search_path(ask_confirmation_func)

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
            log_message(f"Успешно прочитан файл версии: {version_file_path}", "debug")
        except Exception as e:
            log_message(f"Ошибка чтения файла версии {version_file_path}: {e}", 'error')
    return data

def get_current_version(installed_dir):
    version_from_file = None
    version_file = os.path.join(installed_dir, 'version.txt')
    if os.path.exists(version_file):
        version_data = read_version_file(version_file)
        version_from_file = version_data.get('ver')
        if version_from_file:
            log_message(f"Версия определена из version.txt: {version_from_file}", "info")
            return version_from_file
        else:
            log_message("Файл version.txt существует, но не содержит версии.", "warning")
    else:
        log_message("Файл version.txt не найден.", "debug")

    version_from_cache = system_ops.load_cached_version()
    if version_from_cache:
        log_message(f"Версия определена из кеша реестра: {version_from_cache}", "info")
        return version_from_cache

    log_message("Не удалось определить текущую версию ни из файла, ни из кеша.", "warning")
    return None


def download_release_zip(version_to_download, target_zip_path):
    release = github_api.get_latest_github_release(config.REPO_NAME)
    expected_tag = version_to_download
    if not (release and release.tag_name.lstrip('v') == expected_tag):
        log_message(f"Последний релиз не {expected_tag}, ищу по тегу...", "debug")
        try:
            g = github_api.Github()
            repo = g.get_repo(config.REPO_NAME)
            try: release = repo.get_release(f"v{expected_tag}")
            except Exception: release = repo.get_release(expected_tag) # Пробуем без 'v'
        except Exception as e:
            log_message(f"Не удалось найти релиз/тег {expected_tag} на GitHub: {e}", "error")
            return False
        if not release:
            log_message(f"Релиз/тег {expected_tag} не найден.", "error")
            return False
        log_message(f"Найден релиз по тегу: {release.tag_name}", "info")

    zip_asset = None
    expected_filename_v = f"zapret-discord-youtube-v{version_to_download}.zip"
    expected_filename = f"zapret-discord-youtube-{version_to_download}.zip"
    for asset in release.get_assets():
        if asset.name == expected_filename or asset.name == expected_filename_v:
            zip_asset = asset
            break
    if not zip_asset:
        log_message(f"Не найден архив в релизе {version_to_download} ({release.tag_name}).", "error")
        return False

    if filesystem.download_file(zip_asset.browser_download_url, target_zip_path, f"архив Zapret {version_to_download}"):
         log_message("Проверяю целостность скачанного архива...")
         try:
             with filesystem.zipfile.ZipFile(target_zip_path) as zf:
                 bad_file = zf.testzip()
                 if bad_file:
                     log_message(f"Ошибка: Архив поврежден (файл: {bad_file}). Удаляю.", "error")
                     os.remove(target_zip_path)
                     return False
                 else:
                     log_message(f"Архив {version_to_download} успешно проверен.")
                     return True
         except Exception as e:
              log_message(f"Ошибка проверки ZIP: {e}. Удаляю.", "error")
              if os.path.exists(target_zip_path): os.remove(target_zip_path)
              return False
    else:
        return False


def perform_install_or_update(version_to_install, install_dir, is_update=False):
    action = "Обновление" if is_update else "Установка"
    log_message(f"Начинаю {action.lower()} Zapret до версии {version_to_install} в папку: {install_dir}")
    try:
        temp_base_path = os.getenv('TEMP', '.')
        temp_download_path = os.path.join(temp_base_path, config.TEMP_SUBDIR_DOWNLOAD)
        os.makedirs(temp_download_path, exist_ok=True)
        zip_path = os.path.join(temp_download_path, f"zapret-{version_to_install}.zip")
    except Exception as e:
        log_message(f"Ошибка создания временной папки: {e}", "critical")
        return False

    if not download_release_zip(version_to_install, zip_path):
        filesystem.safe_remove_folder(temp_download_path)
        return False

    if is_update:
        system_ops.remove_zapret_services()
        log_message("Завершаю процессы, использующие папку установки...")
        system_ops.kill_processes_using_folder(install_dir)
        log_message("Удаляю старую версию...")
        if not filesystem.safe_remove_folder(install_dir):
            log_message("Критическая ошибка: Не удалось удалить старую версию.", 'error')
            filesystem.safe_remove_folder(temp_download_path)
            return False
    else:
        if os.path.exists(install_dir):
            if not filesystem.safe_remove_folder(install_dir):
                log_message(f"Критическая ошибка: Не удалось очистить {install_dir}.", 'error')
                filesystem.safe_remove_folder(temp_download_path)
                return False

    if not filesystem.unpack_and_move(zip_path, install_dir):
        filesystem.safe_remove_folder(temp_download_path)
        log_message(f"Критическая ошибка: Не удалось распаковать новую версию.", 'error')
        filesystem.safe_remove_folder(install_dir)
        return False

    filesystem.create_desktop_shortcut(install_dir)
    log_message(f"Очистка временных файлов {action.lower()}...")
    filesystem.safe_remove_folder(temp_download_path)

    log_message("-" * 30)
    if is_update:
        log_message(f"УСПЕХ! Zapret обновлен до версии {version_to_install} в '{install_dir}'.")
        log_message(f"Ярлык '{config.SHORTCUT_NAME}' обновлен.")
        log_message("Если использовали службу автозапуска, ее нужно переустановить.")
    else:
        log_message(f"УСПЕХ! Zapret версии {version_to_install} установлен в '{install_dir}'.")
        log_message(f"На рабочем столе создан ярлык '{config.SHORTCUT_NAME}'.")
        log_message("Для автозапуска используйте service_install.bat (от им. Администратора).")
    log_message("-" * 30)

    system_ops.save_cached_path(install_dir)
    system_ops.save_cached_version(version_to_install) # Сохраняем версию в кеш
    return True


def perform_uninstall(install_dir):
    log_message(f"Начинаю удаление Zapret из папки: {install_dir}")
    if not os.path.isdir(install_dir):
        log_message("Папка установки не найдена.", "warning")
        system_ops.clear_updater_cache() # Очищаем кеш на всякий случай
        filesystem.remove_desktop_shortcut()
        return True

    system_ops.remove_zapret_services()
    system_ops.kill_processes_using_folder(install_dir)
    filesystem.remove_desktop_shortcut()

    if filesystem.safe_remove_folder(install_dir):
        log_message("Папка установки успешно удалена.")
        system_ops.clear_updater_cache() # Очищаем кеш после удаления
        log_message("-" * 30)
        log_message("УСПЕХ! Zapret успешно удален.")
        log_message("-" * 30)
        return True
    else:
        log_message("Ошибка: Не удалось полностью удалить папку установки.", "error")
        return False