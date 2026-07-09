import uuid
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class ChatRequestSchema(BaseModel):
    user_id: str = Field(..., description="The user making the request.")
    organization_id: str = Field(..., description="The organization ID for tenant isolation and RAG filtering.")
    conversation_id: uuid.UUID | None = Field(None, description="The conversation ID. Omit to start a new chat.")
    module: str | None = Field(None, description="Optional module filter.")
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The message from the user. Maximum 2000 characters to prevent abuse.",
    )


class ChatResponseSchema(BaseModel):
    conversation_id: str
    reply: str


class MessageResponseSchema(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    meta_data: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationResponseSchema(BaseModel):
    id: uuid.UUID
    organization_id: str | None
    user_id: str | None
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponseSchema] = []

    model_config = ConfigDict(from_attributes=True)
