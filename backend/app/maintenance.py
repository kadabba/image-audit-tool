"""
Обслуживание БД: миграция схемы, ретенция, уборка мусора.
"""

import asyncio
import os
from datetime import datetime, timedelta

from sqlalchemy import text

from .db import SessionLocal, engine
from .models import Image, Scan, ScanStatus, new_scan_token

# Сколько держать сканы. 0 отключает уборку.
RETENTION_DAYS = float(os.getenv("RETENTION_DAYS", "2"))

# Как часто перезапускать уборку. Только при старте её недостаточно:
# сервер живёт неделями, и сканы копились бы до отказа диска.
PURGE_INTERVAL_HOURS = float(os.getenv("PURGE_INTERVAL_HOURS", "6"))

# Уникальность (scan_id, image_url, page_url) по самим URL занимала 42% таблицы:
# два длинных текста в индексе на каждую строку. Хеш даёт ту же гарантию втрое дешевле.
UNIQUE_INDEX = "uq_images_scan_urlhash"

# index=True на первичном ключе создавал вторую копию индекса, который
# PostgreSQL и так строит под PK. Ни один запрос к ним не обращался.
REDUNDANT_INDEXES = ("ix_images_id", "ix_scans_id", "ix_projects_id", "ix_users_id")


def ensure_schema() -> None:
    """
    Доводит существующую БД до текущей схемы.

    Base.metadata.create_all создаёт только отсутствующие таблицы и не умеет
    менять существующие, поэтому миграции делаем здесь.
    """
    with engine.begin() as conn:
        # token у сканов: инкрементный id перебирался и открывал чужие результаты
        conn.execute(text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS token VARCHAR(64)"))
        missing = conn.execute(text("SELECT id FROM scans WHERE token IS NULL")).fetchall()
        for (scan_id,) in missing:
            conn.execute(
                text("UPDATE scans SET token = :t WHERE id = :i"),
                {"t": new_scan_token(), "i": scan_id},
            )
        if missing:
            print(f"Схема: выдан токен {len(missing)} старым сканам")
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_scans_token ON scans (token)"))
        conn.execute(text("ALTER TABLE scans ALTER COLUMN token SET NOT NULL"))

        for name in REDUNDANT_INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))

    # Уникальный индекс строим отдельно: на битых данных он падает,
    # и это не повод не пускать приложение.
    try:
        with engine.begin() as conn:
            conn.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_INDEX} "
                r"ON images (scan_id, md5(image_url || E'\n' || page_url))"
            ))
            conn.execute(text("ALTER TABLE images DROP CONSTRAINT IF EXISTS uq_scan_image_page"))
    except Exception as e:
        print(f"Схема: не удалось перестроить уникальный индекс ({e})")


def recover_stale_scans() -> int:
    """
    Помечает сканы, оборванные рестартом, как failed.

    Фоновая задача живёт в процессе: после перезапуска её никто не продолжит,
    и скан навсегда остался бы в статусе running.
    """
    db = SessionLocal()
    try:
        stale = db.query(Scan).filter(Scan.status == ScanStatus.running).all()
        for scan in stale:
            scan.status = ScanStatus.failed
            scan.completed_at = datetime.utcnow()
        db.commit()
        if stale:
            print(f"Уборка: {len(stale)} оборванных сканов помечены как failed")
        return len(stale)
    finally:
        db.close()


def purge_old_scans(retention_days: float = None) -> int:
    """Удаляет сканы старше срока хранения вместе с их картинками."""
    days = RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=days)
    db = SessionLocal()
    try:
        old_ids = [row[0] for row in db.query(Scan.id).filter(Scan.created_at < cutoff).all()]
        if not old_ids:
            return 0

        removed = db.query(Image).filter(Image.scan_id.in_(old_ids)).delete(synchronize_session=False)
        db.query(Scan).filter(Scan.id.in_(old_ids)).delete(synchronize_session=False)
        db.commit()
        print(f"Ретенция: удалено {len(old_ids)} сканов ({removed} картинок) старше {days} дн.")
        return len(old_ids)
    finally:
        db.close()


async def purge_loop() -> None:
    """Периодическая уборка на всё время жизни процесса."""
    if RETENTION_DAYS <= 0:
        print("Ретенция отключена (RETENTION_DAYS=0)")
        return

    while True:
        await asyncio.sleep(PURGE_INTERVAL_HOURS * 3600)
        try:
            # блокирующий DELETE уводим с event loop, иначе замрёт весь сервер
            await asyncio.to_thread(purge_old_scans)
        except Exception as e:
            print(f"Ретенция: ошибка при уборке ({e})")


def run_startup_tasks() -> None:
    ensure_schema()
    recover_stale_scans()
    purge_old_scans()


def demo():
    """Самопроверка расчёта срока. Запуск: python -m app.maintenance"""
    assert purge_old_scans(0) == 0, "нулевая ретенция должна ничего не удалять"
    assert purge_old_scans(-1) == 0, "отрицательная ретенция должна ничего не удалять"

    # огромный срок не должен задеть свежие сканы
    db = SessionLocal()
    try:
        before = db.query(Scan).count()
    finally:
        db.close()
    assert purge_old_scans(36500) == 0, "столетний срок не должен ничего удалять"
    db = SessionLocal()
    try:
        assert db.query(Scan).count() == before, "сканы пропали при заведомо большом сроке"
    finally:
        db.close()

    print("maintenance: ok")


if __name__ == "__main__":
    demo()
