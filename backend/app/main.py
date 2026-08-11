from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI(title="Image Audit Tool", version="0.1.0")

# Подключаем папку frontend как статика
frontend_dir = os.path.join(os.path.dirname(__file__), "../../frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
async def root():
    """Serve index.html"""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Image Audit Tool API"}


@app.get("/api/health")
async def health():
    """Health check"""
    return {"status": "ok"}


# TODO: Подключить роуты когда они будут готовы
# from app.routes import scan, gallery, export
# app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
# app.include_router(gallery.router, prefix="/api/images", tags=["gallery"])
# app.include_router(export.router, prefix="/api/export", tags=["export"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
