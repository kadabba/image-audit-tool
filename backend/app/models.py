from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    site_url = Column(String(255), nullable=False, index=True)
    image_url = Column(String(2048), nullable=False)
    page_url = Column(String(2048), nullable=False)
    status = Column(String(20), default="NEW", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("site_url", "image_url", "page_url", name="uq_site_image_page"),
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
