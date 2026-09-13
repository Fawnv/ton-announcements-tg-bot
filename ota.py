import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


async def _run_cmd(*args: str, cwd: str = PROJECT_ROOT) -> tuple[int, str]:
    """Запускает команду, возвращает (код возврата, вывод)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode(errors="replace").strip()
    except FileNotFoundError:
        return -1, f"Команда не найдена: {args[0]}"
    except Exception as e:
        return -1, str(e)


async def _run_git(*args: str) -> tuple[int, str]:
    return await _run_cmd("git", *args)


def git_available() -> bool:
    """OTA работает только если бот запущен из git-репозитория."""
    return os.path.isdir(os.path.join(PROJECT_ROOT, ".git"))


async def get_current_commit() -> str:
    code, out = await _run_git("rev-parse", "--short", "HEAD")
    return out if code == 0 else "unknown"


async def check_for_updates() -> dict:
    """Проверяет наличие новых коммитов на origin/main.

    Возвращает dict:
      available: bool
      current / remote: короткие хеши коммитов
      changes: список новых коммитов (oneline)
      error: текст ошибки (если есть)
    """
    if not git_available():
        return {"available": False, "error": "Бот запущен не из git-репозитория — OTA недоступен"}

    code, out = await _run_git("fetch", "origin")
    if code != 0:
        return {"available": False, "error": f"git fetch завершился с ошибкой: {out}"}

    _, current = await _run_git("rev-parse", "--short", "HEAD")
    _, remote = await _run_git("rev-parse", "--short", "origin/main")
    code, changes = await _run_git("log", "--oneline", "HEAD..origin/main")

    return {
        "available": code == 0 and bool(changes),
        "current": current,
        "remote": remote,
        "changes": changes,
    }


async def apply_update() -> tuple[bool, str]:
    """Применяет OTA-обновление: git pull + pip install при изменении зависимостей.

    Возвращает (успех, сообщение).
    """
    if not git_available():
        return False, "Бот запущен не из git-репозитория — OTA недоступен"

    code, out = await _run_git("pull", "--ff-only", "origin", "main")
    if code != 0:
        return False, f"git pull завершился с ошибкой:\n<code>{out}</code>"

    # Если обновился requirements.txt — доустанавливаем зависимости
    code, changed = await _run_git("diff", "--name-only", "ORIG_HEAD", "HEAD")
    if code == 0 and "requirements.txt" in changed.splitlines():
        code, out = await _run_cmd(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        )
        if code != 0:
            return False, f"Обновление кода ок, но pip install упал:\n<code>{out}</code>"

    _, new_commit = await _run_git("rev-parse", "--short", "HEAD")
    return True, new_commit


def restart_bot() -> None:
    """Перезапускает процесс бота без смены PID (работает и в Docker как CMD)."""
    logger.info("Перезапускаю бота (os.execv)...")
    os.execv(sys.executable, [sys.executable] + sys.argv)
