from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db
from ..scanner import scan_site

router = APIRouter()


class ScanRequest(BaseModel):
    site_url: str


class ScanResponse(BaseModel):
    count: int
    new: int
    updated: int


@router.post("/")
async def start_scan(request: ScanRequest, db: Session = Depends(get_db)):
    """
    Запустить сканирование сайта.

    POST /api/scan
    {
        "site_url": "https://example.com"
    }

    Возвращает количество найденных изображений.
    """
    if not request.site_url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http(s)://")

    try:
        result = scan_site(db, request.site_url)
        return ScanResponse(
            count=result["total"],
            new=result["new"],
            updated=result["updated"]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
