from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .routes import scan, gallery, export, proxy

# Swagger открыт по умолчанию для удобства локальной разработки.
# На публичном домене выключается через ENABLE_DOCS=false.
ENABLE_DOCS = os.getenv("ENABLE_DOCS", "true").lower() not in ("false", "0", "no")

app = FastAPI(
    title="Image Audit Tool",
    version="0.1.0",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

# Найди папку frontend (возможные пути)
possible_paths = [
    os.path.join(os.path.dirname(__file__), "../../frontend"),  # При запуске локально
    os.path.join(os.path.dirname(__file__), "../../../frontend"),  # Docker
    os.path.join(os.path.dirname(__file__), "../frontend"),  # Альтернативный путь
    "/app/frontend",  # Абсолютный путь в Docker
]

frontend_dir = None
for path in possible_paths:
    if os.path.exists(path):
        frontend_dir = path
        print(f"Frontend найден: {frontend_dir}")
        break

if frontend_dir:
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
async def root():
    """Serve index.html"""
    if frontend_dir:
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    return {"message": "Image Audit Tool API - frontend not found"}


@app.get("/api/health")
async def health():
    """Health check"""
    return {"status": "ok"}


# Подключаем роуты API
app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
app.include_router(gallery.router, prefix="/api/images", tags=["gallery"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(proxy.router, prefix="/api", tags=["proxy"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
