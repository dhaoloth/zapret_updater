import os

UPDATER_VERSION = "1.0.4"
UPDATER_REPO = "dhaoloth/zapret_updater"
UPDATER_EXE_NAME = "zapret_updater_installer.exe"

REPO_NAME = "Flowseal/zapret-discord-youtube"

TEMP_SUBDIR_DOWNLOAD = 'zapret-temp-dl'
TEMP_SUBDIR_EXTRACT = 'zapret-temp-extract'

MAX_RETRIES = 3
RETRY_DELAY = 5

SHORTCUT_TARGET_BAT = "general.bat"
SHORTCUT_NAME = "Zapret General (Запуск от Админа).lnk"

REGISTRY_KEY_PATH = r"Software\ZapretUpdater"
REGISTRY_VALUE_PATH = "InstallPath"
REGISTRY_VALUE_VERSION = "InstalledVersion" # Новая константа

SERVICES_TO_MANAGE = ["zapret", "WinDivert", "WinDivert14"]

SEARCH_DEPTH_LIMIT = 3
BIN_ESSENTIAL_FILES = {'winws.exe', 'windivert.dll', 'windivert64.sys'} # Должны быть в нижнем регистре

EXCLUDED_DIRS_SEARCH = {
    '$recycle.bin',
    'windows', 'program files', 'program files (x86)', 'programdata',
    'appdata', 'system volume information', 'recovery', 'config.msi',
    'intel', 'amd', 'nvidia', '$windows.~ws', '$windows.~bt',
    'perflogs', 'msocache', 'public', 'drivers', 'temp', 'tmp', '__pycache__',
    'steamlibrary', 'origin games', 'epic games', 'ubisoft game launcher', 'gog games',
    'ea games', 'battle.net', 'android', '.git', '.svn', 'node_modules', 'users'
}