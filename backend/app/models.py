from sqlalchemy import Column, Integer, String, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True)
    site_url = Column(String, nullable=False, index=True)
    image_url = Column(String, nullable=False)
    page_url = Column(String, nullable=False)
    status = Column(String, default="NEW", nullable=False)  # NEW, KEEP, DELETE
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Уникальный ключ: одна запись на (site_url, image_url, page_url)
        {"sqlite_table_options": "UNIQUE(site_url, image_url, page_url)"},
    )

    def to_dict(self):
        return {
            "id": self.id,
            "site_url": self.site_url,
            "image_url": self.image_url,
            "page_url": self.page_url,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }
