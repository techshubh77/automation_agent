from pydantic import BaseModel, Field


class ChatRequestSchema(BaseModel):
    user_id: str | None = Field(None, description="The user making the request.")
    conversation_id: str | None = Field(None, description="The conversation ID. Omit to start a new chat.")
    organization_id: str | None = Field(
        None, description="Optional organization ID filter."
    )
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
