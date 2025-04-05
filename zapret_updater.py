import sys
import os
import time
import subprocess
import ctypes
from packaging import version as pkg_version
import datetime

import config
import logger_setup
import github_api
import system_ops
import filesystem
import zapret_ops
import self_update

logger_setup.setup_logging()
log_message = logger_setup.log_message

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

def show_main_menu(installed_dir, current_version, latest_zapret_version):
    while True:
        current_version = zapret_ops.get_current_version(installed_dir)
        if not current_version:
             log_message("Не удалось перечитать текущую версию Zapret.", "warning")
        print("\n--- Меню Управления Zapret ---")
        print(f" Установлен в: {installed_dir}")
        print(f" Текущая версия: {current_version if current_version else 'Неизвестно'}")
        print(f" Последняя версия: {latest_zapret_version if latest_zapret_version else 'Неизвестно'}")
        print("-" * 30)
        print("1. Проверить и установить обновления Zapret (если доступны)")
        print("2. Переустановить/Починить Zapret (установить последнюю версию)")
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
            elif not latest_zapret_version:
                log_message("Не удалось получить последнюю версию Zapret для сравнения.", "warning")
                print("Не удалось проверить наличие обновлений Zapret.")
                continue
            elif latest_zapret_version != current_version:
                 try:
                     if pkg_version.parse(latest_zapret_version) > pkg_version.parse(current_version):
                         update_needed = True
                         reason = f"доступна новая версия {latest_zapret_version}"
                     else:
                         reason = f"установлена последняя или более новая версия ({current_version})"
                 except Exception as e:
                     log_message(f"Ошибка сравнения версий Zapret: {e}. Предлагаем обновиться.", "warning")
                     update_needed = True
                     reason = "ошибка сравнения версий"
            else:
                reason = f"установлена последняя версия ({current_version})"

            log_message(f"Результат проверки обновлений Zapret: {reason}.")
            if update_needed:
                if ask_for_user_confirmation(f"Доступно обновление Zapret до версии {latest_zapret_version} ({reason}). Начать обновление?"):
                    zapret_ops.perform_install_or_update(latest_zapret_version, installed_dir, is_update=True)
                else:
                    log_message("Обновление Zapret отменено пользователем.")
            else:
                print("Обновление Zapret не требуется. У вас установлена последняя версия.")
                log_message("Обновление Zapret не требуется.")
            input("Нажмите Enter для возврата в меню...")

        elif choice == '2':
            if not latest_zapret_version:
                log_message("Не удалось получить последнюю версию Zapret для переустановки.", "error")
                print("Невозможно выполнить переустановку: не удалось определить последнюю версию Zapret.")
                continue
            if ask_for_user_confirmation(f"Вы уверены, что хотите переустановить Zapret (версия {latest_zapret_version}) в папку '{installed_dir}'? Существующие файлы будут удалены."):
                zapret_ops.perform_install_or_update(latest_zapret_version, installed_dir, is_update=True)
            else:
                log_message("Переустановка Zapret отменена пользователем.")
            input("Нажмите Enter для возврата в меню...")

        elif choice == '3':
            if ask_for_user_confirmation(f"ВНИМАНИЕ! Вы уверены, что хотите ПОЛНОСТЬЮ удалить Zapret из папки '{installed_dir}', включая службы и ярлык?"):
                zapret_ops.perform_uninstall(installed_dir)
                return True # Выход из меню и программы после удаления
            else:
                log_message("Удаление Zapret отменено пользователем.")
            input("Нажмите Enter для возврата в меню...")

        elif choice == '0':
            log_message("Выход из программы по выбору пользователя.")
            return False 

        else:
            print("Неверный выбор. Пожалуйста, введите номер из меню.")


def run_main_logic():
    log_message("-" * 50)
    log_message("Запуск установщика/обновления Zapret для Discord/YouTube")
    log_message(f"Репозиторий обновлятора: {config.UPDATER_REPO}")
    log_message(f"Версия обновлятора: {config.UPDATER_VERSION}")
    log_message(f"Время запуска: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_message("-" * 50)

    if not system_ops.is_admin():
         log_message("Критическая ошибка: Скрипт запущен без прав Администратора!", "critical")
         log_message("Пожалуйста, перезапустите скрипт с правами Администратора.", "critical")
         return

    if self_update.check_self_update(ask_for_user_confirmation):
        sys.exit(0)

    installed_dir = zapret_ops.search_installation(ask_for_user_confirmation)

    zapret_release = github_api.get_latest_github_release(config.REPO_NAME)
    latest_zapret_version = zapret_release.tag_name.lstrip('v') if zapret_release else None

    if not installed_dir:
        log_message("Программа Zapret не найдена на этом компьютере.")
        if not latest_zapret_version:
             log_message("Не удалось получить информацию о последней версии Zapret с GitHub.", 'error')
             log_message("Установка невозможна. Проверьте интернет-соединение и доступность GitHub.", 'error')
             return

        if ask_for_user_confirmation(f"Хотите установить последнюю версию Zapret ({latest_zapret_version}) сейчас?"):
            chosen_path = filesystem.ask_for_path_dialog(
                title="Выберите папку для НОВОЙ установки Zapret"
            )
            if chosen_path:
                if not filesystem.check_write_permission(chosen_path):
                    return # Ошибка уже залогирована
                if os.path.exists(chosen_path) and os.listdir(chosen_path):
                     if not ask_for_user_confirmation(f"ВНИМАНИЕ: Папка '{chosen_path}' не пуста. Хотите удалить ее содержимое и продолжить установку?"):
                         log_message("Установка отменена пользователем из-за непустой папки.")
                         return

                zapret_ops.perform_install_or_update(latest_zapret_version, chosen_path, is_update=False)
            else:
                log_message("Папка для установки не выбрана. Установка отменена.")
        else:
            log_message("Установка отменена пользователем.")
    else:
        # Установка найдена, показываем меню
        current_version = zapret_ops.get_current_version(installed_dir)
        if not current_version:
            log_message("Не удалось определить версию установленной программы Zapret (файл version.txt отсутствует или поврежден).", "warning")

        exit_after_menu = show_main_menu(installed_dir, current_version, latest_zapret_version)
        if exit_after_menu:
             return 


if __name__ == "__main__":
    elevated_param = '--elevated'

    if elevated_param not in sys.argv and not system_ops.is_admin():
        log_message("Для работы требуются права Администратора.", 'warning')
        log_message("Запрос на повышение прав (UAC)...", 'info')
        time.sleep(1)

        try:
            script_path = os.path.abspath(sys.argv[0])
            params = [elevated_param] + sys.argv[1:]
            params_string = subprocess.list2cmdline(params)

            # Определяем, запускаемся из python или exe
            executable_to_run = sys.executable

            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", executable_to_run, f'"{script_path}" {params_string}', None, 1
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
            if logger_setup.logger: logger_setup.logger.exception(e)
            print("\nПроизошла ошибка при попытке запросить права Администратора.")
            input("Нажмите Enter для выхода...")
            sys.exit(1)

    if elevated_param in sys.argv:
        sys.argv.remove(elevated_param)
        log_message("Скрипт перезапущен с правами администратора.", 'info')
    elif system_ops.is_admin():
         log_message("Скрипт уже запущен с правами администратора.", 'info')
    else:
         log_message("Критическая ошибка: Не удалось получить права администратора.", "critical")
         input("Нажмите Enter для выхода...")
         sys.exit(1)


    try:
        run_main_logic()
    except Exception as e:
        log_message("Произошла критическая непредвиденная ошибка:", 'critical')
        if logger_setup.logger: logger_setup.logger.exception(e)
        print("\nПроизошла критическая ошибка. Подробности в лог-файле.")

    # --- Завершение работы ---
    print("\nРабота программы завершена.")
    input("Нажмите Enter для закрытия окна...")