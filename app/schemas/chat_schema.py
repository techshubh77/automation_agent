import uuid

from pydantic import BaseModel, Field


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
    reply: str
    conversation_id: str
