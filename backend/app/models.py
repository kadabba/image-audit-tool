from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, Enum, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import enum
import secrets


def new_scan_token() -> str:
    """Непредсказуемый идентификатор скана для внешних ссылок."""
    return secrets.token_urlsafe(16)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    projects = relationship("Project", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    site_url = Column(String(255), nullable=False, index=True)
    name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="projects")
    scans = relationship("Scan", back_populates="project")


class ScanStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    # Наружу отдаём только token: инкрементный id перебирается и открывает чужие сканы
    token = Column(String(64), unique=True, index=True, nullable=False, default=new_scan_token)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    status = Column(Enum(ScanStatus), default=ScanStatus.pending, nullable=False)
    total_pages = Column(Integer, default=0)
    scanned_pages = Column(Integer, default=0)  # текущий прогресс
    total_images = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)  # когда началось сканирование
    completed_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="scans")
    images = relationship("Image", back_populates="scan")


class CopyrightScore(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    page_url = Column(String(2048), nullable=False)
    image_url = Column(String(2048), nullable=False)
    status = Column(String(20), default="NEW", nullable=False)

    # Технический аудит
    http_status = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=True)
    format = Column(String(50), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    # Copyright аудит
    exif_data = Column(JSON, nullable=True)
    copyright_score = Column(Enum(CopyrightScore), default=CopyrightScore.low)
    risk_details = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("scan_id", "image_url", "page_url", name="uq_scan_image_page"),
    )

    scan = relationship("Scan", back_populates="images")

    def to_dict(self):
        return {
            "id": self.id,
            "scan_id": self.scan_id,
            "page_url": self.page_url,
            "image_url": self.image_url,
            "status": self.status,
            "http_status": self.http_status,
            "file_size": self.file_size,
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "copyright_score": self.copyright_score.value if self.copyright_score else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }
