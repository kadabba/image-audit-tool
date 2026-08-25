"""Ограничение запусков сканирования: по IP и по общей нагрузке."""

import time
from collections import deque
from threading import Lock

SCANS_PER_HOUR = 5
WINDOW_SECONDS = 3600
MAX_CONCURRENT_SCANS = 3

_SWEEP_EVERY = 300  # как часто выбрасывать протухшие IP из памяти

# ponytail: состояние живёт в памяти процесса — хватает на один uvicorn-воркер.
# Появятся воркеры или реплики — переносить счётчики в Redis.
_lock = Lock()
_starts: dict[str, deque] = {}
_running = 0
_last_sweep = 0.0


class RateLimited(Exception):
    """Лимит исчерпан. В сообщении — что сказать пользователю."""


def _sweep(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < _SWEEP_EVERY:
        return
    _last_sweep = now
    for ip in [ip for ip, q in _starts.items() if not q or now - q[-1] > WINDOW_SECONDS]:
        del _starts[ip]


def check_and_reserve(client_ip: str) -> None:
    """
    Разрешает запуск скана для IP или бросает RateLimited.

    При успехе занимает слот — освободить через release().
    """
    global _running
    now = time.monotonic()

    with _lock:
        _sweep(now)

        q = _starts.get(client_ip)
        if q is None:
            q = _starts[client_ip] = deque()
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()

        if len(q) >= SCANS_PER_HOUR:
            minutes = int((WINDOW_SECONDS - (now - q[0])) // 60) + 1
            raise RateLimited(
                f"Исчерпан лимит {SCANS_PER_HOUR} сканирований в час. "
                f"Следующее будет доступно через {minutes} мин."
            )

        if _running >= MAX_CONCURRENT_SCANS:
            raise RateLimited(
                "Сейчас выполняется максимум одновременных сканирований. "
                "Попробуйте через пару минут."
            )

        q.append(now)
        _running += 1


def release() -> None:
    """Освобождает слот после завершения скана."""
    global _running
    with _lock:
        _running = max(0, _running - 1)


def _reset_for_tests() -> None:
    global _running, _last_sweep
    with _lock:
        _starts.clear()
        _running = 0
        _last_sweep = 0.0


def demo():
    _reset_for_tests()

    # лимит по IP срабатывает на SCANS_PER_HOUR+1 запуске
    for _ in range(SCANS_PER_HOUR):
        check_and_reserve("1.1.1.1")
        release()
    try:
        check_and_reserve("1.1.1.1")
        raise AssertionError("должен был сработать лимит по IP")
    except RateLimited as e:
        assert "в час" in str(e), e

    # чужой IP лимитом соседа не задет
    _reset_for_tests()
    for _ in range(SCANS_PER_HOUR):
        check_and_reserve("1.1.1.1")
        release()
    check_and_reserve("2.2.2.2")
    release()

    # общий потолок одновременных сканов
    _reset_for_tests()
    for i in range(MAX_CONCURRENT_SCANS):
        check_and_reserve(f"10.0.0.{i}")  # слоты заняты, release не зовём
    try:
        check_and_reserve("10.0.0.99")
        raise AssertionError("должен был сработать потолок одновременных")
    except RateLimited as e:
        assert "одновременных" in str(e), e

    # освободили слот — снова можно
    release()
    check_and_reserve("10.0.0.99")
    release()

    _reset_for_tests()
    print("ratelimit: ok")


if __name__ == "__main__":
    demo()
