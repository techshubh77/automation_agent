import enum
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class UsageStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class CreditUsage(BaseModel):
    __tablename__ = "credit_usage"

    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    operation_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    credits_used: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0.0"), nullable=False)
    status: Mapped[UsageStatus] = mapped_column(
        Enum(
            UsageStatus,
            name="credit_usage_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj]
        ),
        index=True,
        default=UsageStatus.COMPLETED,
        nullable=False
    )

    cost_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)

    # Relationships
    organization = relationship("Organization")
