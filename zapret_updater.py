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
        except RuntimeError as e: # Добавлено для обработки lost sys.stdin и здесь
             log_message(f"Ошибка ввода ({e}). Считаем ответ 'n'.", "error")
             print(f"\nОшибка чтения ввода: {e}. Автоматически выбран ответ 'Нет'.")
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

        choice = ""
        try:
            choice = input("Выберите действие (введите номер): ").strip()
        except RuntimeError as e:
             log_message(f"Ошибка ввода в меню ({e}). Выход из меню.", "error")
             print(f"\nОшибка чтения ввода: {e}. Выход из программы.")
             return False # Выходим из меню и программы
        except EOFError:
             log_message("Ввод не удался (EOF) в меню. Выход из меню.", "warning")
             print("\nОшибка чтения ввода. Выход из программы.")
             return False

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
            input_pause_or_exit("Нажмите Enter для возврата в меню...")

        elif choice == '2':
            if not latest_zapret_version:
                log_message("Не удалось получить последнюю версию Zapret для переустановки.", "error")
                print("Невозможно выполнить переустановку: не удалось определить последнюю версию Zapret.")
                continue
            if ask_for_user_confirmation(f"Вы уверены, что хотите переустановить Zapret (версия {latest_zapret_version}) в папку '{installed_dir}'? Существующие файлы будут удалены."):
                zapret_ops.perform_install_or_update(latest_zapret_version, installed_dir, is_update=True)
            else:
                log_message("Переустановка Zapret отменена пользователем.")
            input_pause_or_exit("Нажмите Enter для возврата в меню...")

        elif choice == '3':
            if ask_for_user_confirmation(f"ВНИМАНИЕ! Вы уверены, что хотите ПОЛНОСТЬЮ удалить Zapret из папки '{installed_dir}', включая службы и ярлык?"):
                zapret_ops.perform_uninstall(installed_dir)
                return True # Выход из меню и программы после удаления
            else:
                log_message("Удаление Zapret отменено пользователем.")
            input_pause_or_exit("Нажмите Enter для возврата в меню...")

        elif choice == '0':
            log_message("Выход из программы по выбору пользователя.")
            return False

        else:
            print("Неверный выбор. Пожалуйста, введите номер из меню.")

def input_pause_or_exit(message="Нажмите Enter для продолжения..."):
    """Обертка для input(), обрабатывающая ошибки stdin."""
    try:
        input(message)
    except RuntimeError as e:
        log_message(f"Ошибка input() при паузе ({e}). Продолжение без паузы.", "warning")
        print(f"\n(Ошибка ожидания ввода: {e}, продолжение...)")
        time.sleep(2) # Небольшая пауза вместо input
    except EOFError:
        log_message("EOFError при паузе. Продолжение без паузы.", "warning")
        print("\n(Ошибка ожидания ввода, продолжение...)")
        time.sleep(2)


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
         # Не используем input_pause_or_exit здесь, т.к. stdin может быть уже потерян
         print("Критическая ошибка: Скрипт запущен без прав Администратора!")
         print("Пожалуйста, перезапустите скрипт с правами Администратора.")
         time.sleep(5)
         return # Просто выход

    if self_update.check_self_update(ask_for_user_confirmation):
        # Самообновление запущено, текущий процесс должен завершиться
        # Не вызываем здесь input_pause_or_exit, т.к. скрипт должен тихо умереть
        sys.exit(0)

    installed_dir = zapret_ops.search_installation(ask_for_user_confirmation)

    zapret_release = github_api.get_latest_github_release(config.REPO_NAME)
    latest_zapret_version = zapret_release.tag_name.lstrip('v') if zapret_release else None

    if not installed_dir:
        log_message("Программа Zapret не найдена на этом компьютере.")
        if not latest_zapret_version:
             log_message("Не удалось получить информацию о последней версии Zapret с GitHub.", 'error')
             log_message("Установка невозможна. Проверьте интернет-соединение и доступность GitHub.", 'error')
             print("Ошибка: Не удалось получить информацию о последней версии Zapret с GitHub.")
             print("Установка невозможна. Проверьте интернет и доступность GitHub.")
             return # Выход без паузы

        if ask_for_user_confirmation(f"Хотите установить последнюю версию Zapret ({latest_zapret_version}) сейчас?"):
            chosen_path = filesystem.ask_for_path_dialog(
                title="Выберите папку для НОВОЙ установки Zapret"
            )
            if chosen_path:
                if not filesystem.check_write_permission(chosen_path):
                    # Ошибка залогирована, выход без паузы
                    print("Ошибка: Нет прав на запись в выбранную папку.")
                    time.sleep(3)
                    return
                if os.path.exists(chosen_path) and os.listdir(chosen_path):
                     if not ask_for_user_confirmation(f"ВНИМАНИЕ: Папка '{chosen_path}' не пуста. Хотите удалить ее содержимое и продолжить установку?"):
                         log_message("Установка отменена пользователем из-за непустой папки.")
                         print("Установка отменена.")
                         return # Выход без паузы

                zapret_ops.perform_install_or_update(latest_zapret_version, chosen_path, is_update=False)
            else:
                log_message("Папка для установки не выбрана. Установка отменена.")
                print("Установка отменена.")
        else:
            log_message("Установка отменена пользователем.")
            print("Установка отменена.")
    else:
        # Установка найдена, показываем меню
        current_version = zapret_ops.get_current_version(installed_dir)
        if not current_version:
            log_message("Не удалось определить версию установленной программы Zapret (файл version.txt отсутствует или поврежден).", "warning")
            print("Предупреждение: Не удалось определить текущую версию Zapret.")

        exit_after_menu = show_main_menu(installed_dir, current_version, latest_zapret_version)
        if exit_after_menu:
             log_message("Выход после удаления.")
             return # Выход без паузы


if __name__ == "__main__":
    elevated_param = '--elevated'

    # --- Блок запроса прав Администратора ---
    if elevated_param not in sys.argv and not system_ops.is_admin():
        log_message("Для работы требуются права Администратора.", 'warning')
        log_message("Запрос на повышение прав (UAC)...", 'info')
        print("Запрашиваю права администратора (UAC)...") # Сообщение пользователю
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
                # Используем time.sleep вместо input для выхода
                time.sleep(7)
                sys.exit(1) # Выход из оригинального процесса
            else:
                log_message("Запрос на повышение прав отправлен. Исходный процесс завершается...", 'info')
                # Не нужно ждать input, просто выходим
                sys.exit(0) # Успешный запуск нового процесса, старый завершаем
        except Exception as e:
            log_message(f"Исключение при попытке перезапуска с повышением прав: {e}", 'critical')
            if logger_setup.logger: logger_setup.logger.exception(e)
            print("\nПроизошла ошибка при попытке запросить права Администратора.")
            # Используем time.sleep вместо input для выхода
            time.sleep(7)
            sys.exit(1)

    # --- Основная логика после проверки/получения прав ---
    if elevated_param in sys.argv:
        sys.argv.remove(elevated_param)
        log_message("Скрипт перезапущен с правами администратора.", 'info')
    elif system_ops.is_admin():
         log_message("Скрипт уже запущен с правами администратора.", 'info')
    else:
         # Эта ветка не должна выполняться, если логика выше верна
         log_message("Критическая ошибка: Не удалось получить права администратора после проверки.", "critical")
         print("Критическая ошибка: Не удалось получить права администратора.")
         time.sleep(5)
         sys.exit(1)


    # --- Запуск основной логики ---
    try:
        run_main_logic()
    except Exception as e:
        log_message("Произошла критическая непредвиденная ошибка:", 'critical')
        if logger_setup.logger: logger_setup.logger.exception(e)
        print(f"\nПроизошла критическая ошибка: {e}")
        print("Подробности смотрите в лог-файле.")
        # Пауза перед выходом в случае критической ошибки
        input_pause_or_exit("Нажмите Enter для закрытия окна...")
        sys.exit(1) # Завершение с кодом ошибки


    # --- Завершение работы ---
    print("\nРабота программы завершена.")
    log_message("Работа программы успешно завершена.", "info")
    # Используем обертку input_pause_or_exit здесь
    input_pause_or_exit("Нажмите Enter для закрытия окна...")
    sys.exit(0) # Успешное завершение