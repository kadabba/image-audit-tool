from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db
from ..scanner import scan_site
from ..models import User, Project, Scan, ScanStatus

router = APIRouter()


class ScanRequest(BaseModel):
    site_url: str


class ScanResponse(BaseModel):
    count: int
    scan_id: int


@router.post("/")
async def start_scan(request: ScanRequest, db: Session = Depends(get_db)):
    """
    Запустить сканирование сайта.

    POST /api/scan
    {
        "site_url": "https://example.com"
    }

    Очищает старые данные для этого сайта и сканирует его заново.
    Возвращает количество найденных изображений и scan_id.
    """
    if not request.site_url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http(s)://")

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

        # Запускаем сканирование
        result = scan_site(db, scan.id, request.site_url)

        # Обновляем статус сканирования
        scan.status = ScanStatus.completed
        scan.total_images = result["count"]
        db.commit()

        return ScanResponse(count=result["count"], scan_id=scan.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
