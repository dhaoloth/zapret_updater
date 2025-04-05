import requests
import time
from github import Github
from github.GithubException import RateLimitExceededException, GithubException, UnknownObjectException

from logger_setup import log_message
import config

def get_latest_github_release(repo_name):
    log_message(f"Запрашиваю информацию о последнем релизе с GitHub ({repo_name})...")
    g = Github()
    retries = config.MAX_RETRIES
    for attempt in range(retries):
        try:
            repo = g.get_repo(repo_name)
            latest_release = repo.get_latest_release()
            log_message(f"Последний релиз на GitHub ({repo_name}): {latest_release.tag_name}")
            return latest_release
        except RateLimitExceededException:
            wait = config.RETRY_DELAY * (attempt + 1)
            log_message(f"Превышен лимит запросов к GitHub API. Жду {wait} сек...", 'warning')
            time.sleep(wait)
        except UnknownObjectException:
             log_message(f"Ошибка: Репозиторий {repo_name} не найден или не содержит релизов.", 'error')
             return None
        except GithubException as e:
            log_message(f"Ошибка GitHub API ({repo_name}, попытка {attempt + 1}/{retries}): {e}", 'error')
            time.sleep(config.RETRY_DELAY)
        except requests.exceptions.RequestException as e:
             log_message(f"Сетевая ошибка при запросе к GitHub ({repo_name}, попытка {attempt + 1}/{retries}): {e}", 'error')
             time.sleep(config.RETRY_DELAY)
    log_message(f"Не удалось получить информацию о последнем релизе с GitHub ({repo_name}) после нескольких попыток.", 'error')
    return None