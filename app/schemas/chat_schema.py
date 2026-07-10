import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequestSchema(BaseModel):
    user_id: str = Field(..., description="The user making the request.")
    organization_id: str = Field(
        ..., description="The organization ID for tenant isolation and RAG filtering."
    )
    conversation_id: uuid.UUID | None = Field(
        None, description="The conversation ID. Omit to start a new chat."
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
        description="The conversational reply to the user. If fields are missing, politely ask for them."
    )
    flag: bool = Field(
        description="True ONLY if the user has provided all required information and the payload is ready to be sent to Laravel."
    )

    # When flag is True:
    payload: AgentActionPayload | None = Field(
        default=None,
        description="The complete payload containing endpoint, method, and data to execute the action.",
    )

    # When flag is False:
    missing_fields: list[str] | None = Field(
        default=None,
        description="A simple list of short strings describing the missing fields (e.g. 'title: Short summary of the issue').",
    )
    payload_example: dict | None = Field(
        default=None,
        description="A complete example of just the DATA payload (do NOT include endpoint or method here, only the fields the user needs to provide).",
    )


class ChatResponseSchema(BaseModel):
    conversation_id: str
    reply: str
    flag: bool = False
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
