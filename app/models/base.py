import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """
    The master Base class for all SQLAlchemy Models.
    Every table in the database will inherit from this.
    """

    pass


class UUIDMixin:
    """
    Mixin that provides a standardized UUID primary key.
    Enterprise standard: Prevents ID enumeration attacks (unlike auto-incrementing integers).
    """

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )


class TimestampMixin:
    """
    Mixin that automatically adds 'created_at' and 'updated_at' columns.
    Matches the behavior of Sequelize's automatic timestamps.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),  # Automatically updates on row modification
        nullable=False,
    )


class BaseModel(Base, UUIDMixin, TimestampMixin):
    """
    A convenience class combining Base, UUID, and Timestamps.
    Inherit from this for 99% of your database models.

    Example:
        class User(BaseModel):
            __tablename__ = "users"
            email: Mapped[str] = mapped_column(unique=True)
    """

    __abstract__ = (
        True  # Tells SQLAlchemy not to create a table for this specific class
    )
