"""
Обслуживание БД при старте: миграция схемы, уборка мусора, ретенция.
"""

import os
from datetime import datetime, timedelta

from sqlalchemy import text

from .db import SessionLocal, engine
from .models import Image, Scan, ScanStatus, new_scan_token

# Сколько держать сканы. 0 отключает уборку.
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))


def ensure_schema() -> None:
    """
    Доводит существующую БД до текущей схемы.

    Base.metadata.create_all создаёт только отсутствующие таблицы и не умеет
    добавлять колонки, поэтому база, созданная до появления Scan.token,
    падала бы на первом же запросе.
    """
    with engine.begin() as conn:
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


def purge_old_scans(retention_days: int = RETENTION_DAYS) -> int:
    """Удаляет сканы старше срока хранения вместе с их картинками."""
    if retention_days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    db = SessionLocal()
    try:
        old_ids = [s.id for s in db.query(Scan.id).filter(Scan.created_at < cutoff).all()]
        if not old_ids:
            return 0

        db.query(Image).filter(Image.scan_id.in_(old_ids)).delete(synchronize_session=False)
        db.query(Scan).filter(Scan.id.in_(old_ids)).delete(synchronize_session=False)
        db.commit()
        print(f"Ретенция: удалено {len(old_ids)} сканов старше {retention_days} дн.")
        return len(old_ids)
    finally:
        db.close()


def run_startup_tasks() -> None:
    ensure_schema()
    recover_stale_scans()
    purge_old_scans()
