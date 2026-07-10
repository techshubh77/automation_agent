import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class TokenUsage(BaseModel):
    __tablename__ = "token_usage"

    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True, nullable=True
    )
    operation_type: Mapped[str] = mapped_column(String, index=True, nullable=False)

    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Relationships
    organization = relationship("Organization")
    conversation = relationship("Conversation")
