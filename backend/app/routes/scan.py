from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db, SessionLocal
from ..scanner import scan_site_async
from ..models import User, Project, Scan, ScanStatus
from ..net_guard import check_public_url
from .. import ratelimit
from ..maintenance import RETENTION_DAYS
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter()


class ScanRequest(BaseModel):
    site_url: str


class ScanResponse(BaseModel):
    count: int
    scan_token: str
    status: str


class ScanStatusResponse(BaseModel):
    token: str
    status: str
    site_url: str
    total_images: int
    total_pages: int
    scanned_pages: int
    progress: int  # 0-100%
    # Срок считает сервер: только он знает RETENTION_DAYS
    expires_at: Optional[str] = None


def get_scan_by_token(token: str, db: Session) -> Scan:
    """
    Ищет скан по токену. Единственный способ добраться до скана снаружи:
    инкрементный id перебирается и открывал бы чужие результаты.
    """
    scan = db.query(Scan).filter(Scan.token == token).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Сканирование не найдено")
    return scan


async def _run_scan_background(scan_id: int, site_url: str):
    """Фоновое сканирование в отдельной сессии БД"""
    db = SessionLocal()
    try:
        result = await scan_site_async(db, scan_id, site_url)
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.status = ScanStatus.completed
            scan.total_images = result["unique"]
            scan.completed_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        # откат обязателен: после упавшего flush сессия не примет запись статуса
        db.rollback()
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.status = ScanStatus.failed
            scan.completed_at = datetime.utcnow()
            db.commit()
        print(f"Ошибка при сканировании: {e}")
    finally:
        db.close()
        ratelimit.release()


@router.post("/")
async def start_scan(
    request: ScanRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Запустить сканирование сайта.

    POST /api/scan
    {
        "site_url": "https://example.com"
    }

    Возвращает scan_token — по нему потом читается прогресс и галерея.
    """
    try:
        check_public_url(request.site_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    client_ip = http_request.client.host if http_request.client else "unknown"
    try:
        ratelimit.check_and_reserve(client_ip)
    except ratelimit.RateLimited as e:
        raise HTTPException(status_code=429, detail=str(e))

    try:
        # Для MVP: используем или создаём default user и project
        user = db.query(User).filter(User.email == "default@local").first()
        if not user:
            user = User(email="default@local", name="Default User")
            db.add(user)
            db.commit()
            db.refresh(user)

        project = db.query(Project).filter(
            Project.user_id == user.id,
            Project.site_url == request.site_url
        ).first()
        if not project:
            project = Project(user_id=user.id, site_url=request.site_url, name=request.site_url)
            db.add(project)
            db.commit()
            db.refresh(project)

        # Создаём новый Scan
        scan = Scan(project_id=project.id, status=ScanStatus.running)
        db.add(scan)
        db.commit()
        db.refresh(scan)

        # Запускаем сканирование в фоне
        background_tasks.add_task(_run_scan_background, scan.id, request.site_url)

        return ScanResponse(count=0, scan_token=scan.token, status="running")
    except HTTPException:
        ratelimit.release()
        raise
    except Exception as e:
        # фоновая задача не стартует — слот освобождаем здесь, иначе он утечёт
        ratelimit.release()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{token}")
async def get_scan_status(token: str, db: Session = Depends(get_db)):
    """
    Получить статус сканирования с прогрессом.

    GET /api/scan/{token}
    """
    scan = get_scan_by_token(token, db)

    # Рассчитываем прогресс
    progress = 0
    if scan.total_pages and scan.total_pages > 0:
        progress = min(100, int((scan.scanned_pages or 0) * 100 / scan.total_pages))

    expires_at = None
    if RETENTION_DAYS > 0 and scan.created_at:
        expires_at = (scan.created_at + timedelta(days=RETENTION_DAYS)).isoformat()

    return ScanStatusResponse(
        token=scan.token,
        status=scan.status.value,
        site_url=scan.project.site_url if scan.project else "",
        total_images=scan.total_images or 0,
        total_pages=scan.total_pages or 0,
        scanned_pages=scan.scanned_pages or 0,
        progress=progress,
        expires_at=expires_at,
    )
