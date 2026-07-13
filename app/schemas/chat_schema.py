import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequestSchema(BaseModel):
    user_id: str = Field(..., description="The user making the request.")
    organization_id: str = Field(
        ..., description="The organization ID for tenant isolation and RAG filtering."
    )
    conversation_id: uuid.UUID | None = Field(
        default=None,
        description="The conversation ID. Omit to start a new chat.",
        json_schema_extra={"example": None}
    )
    module: str | None = Field(None, description="Optional module filter.")
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The message from the user. Maximum 2000 characters to prevent abuse.",
    )


class AgentActionPayload(BaseModel):
    endpoint: str = Field(
        description="The API endpoint to call (e.g., /api/v1/leaves)."
    )
    method: str = Field(description="The HTTP method to use (e.g., POST, PUT, DELETE).")
    data: dict = Field(
        description="The actual JSON payload data to send to the endpoint."
    )


class AgentResponse(BaseModel):
    reply: str = Field(
        description="Your conversational response to the user. In Stage 3 (flag=true), say a short confirmation like 'Done! Creating your ticket now.'"
    )
    flag: bool = Field(
        description="True ONLY in Stage 3, when the user has just confirmed the preview and the action is being executed."
    )
    preview: bool = Field(
        description="MUST be true if missing_fields is empty [] (Stage 2). MUST be false if there are missing fields (Stage 1) or if the user confirmed (Stage 3). If you have all fields, you are FORBIDDEN from setting this to false."
    )

    # Populated ONLY in Stage 3:
    payload: AgentActionPayload | None = Field(
        default=None,
        description="The final action payload with endpoint, method, and data. Populated ONLY when flag=true.",
    )

    # Populated in Stage 1 and Stage 2:
    missing_fields: list[str] = Field(
        description="Fields that are truly missing and cannot be inferred. Empty list [] in Stage 2 and Stage 3. NEVER include 'title' or 'description' if the user provided any descriptive context at all.",
    )
    payload_example: dict = Field(
        description="The data dict showing what you have inferred or extracted so far. In Stage 1, show partial data already inferred. In Stage 2, show the complete confirmed data. Empty dict {} in Stage 3 and Mode A (pure conversation).",
    )


class ChatResponseSchema(BaseModel):
    conversation_id: str
    reply: str
    flag: bool = False
    preview: bool = False
    payload: dict | None = None
    missing_fields: list[str] | None = None
    payload_example: dict | None = None


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
