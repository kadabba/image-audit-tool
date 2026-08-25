from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db, SessionLocal
from ..scanner import scan_site_async
from ..models import User, Project, Scan, ScanStatus
from ..net_guard import check_public_url
from .. import ratelimit
import asyncio

router = APIRouter()


class ScanRequest(BaseModel):
    site_url: str


class ScanResponse(BaseModel):
    count: int
    scan_id: int
    status: str


class ScanStatusResponse(BaseModel):
    id: int
    status: str
    total_images: int
    total_pages: int
    scanned_pages: int
    progress: int  # 0-100%


async def _run_scan_background(scan_id: int, site_url: str, enable_seo: bool = False):
    """Фоновое сканирование в отдельной сессии БД"""
    db = SessionLocal()
    try:
        result = await scan_site_async(db, scan_id, site_url, enable_seo=enable_seo)
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.status = ScanStatus.completed
            scan.total_images = result["count"]
            db.commit()
    except Exception as e:
        # откат обязателен: после упавшего flush сессия не примет запись статуса
        db.rollback()
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.status = ScanStatus.failed
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

    Очищает старые данные для этого сайта и сканирует его заново.
    Возвращает количество найденных изображений и scan_id.
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

        return ScanResponse(count=0, scan_id=scan.id, status="running")
    except Exception as e:
        # фоновая задача не стартует — слот освобождаем здесь, иначе он утечёт
        ratelimit.release()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{scan_id}")
async def get_scan_status(scan_id: int, db: Session = Depends(get_db)):
    """
    Получить статус сканирования с прогрессом.

    GET /api/scans/123
    """
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Сканирование не найдено")

    # Рассчитываем прогресс
    progress = 0
    if scan.total_pages and scan.total_pages > 0:
        progress = min(100, int((scan.scanned_pages or 0) * 100 / scan.total_pages))

    return ScanStatusResponse(
        id=scan.id,
        status=scan.status.value,
        total_images=scan.total_images or 0,
        total_pages=scan.total_pages or 0,
        scanned_pages=scan.scanned_pages or 0,
        progress=progress
    )
