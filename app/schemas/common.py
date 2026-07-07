from pydantic import BaseModel, ConfigDict


class ORMSchema(BaseModel):
    """
    Base schema for data validation (This is your Joi replacement).
    `from_attributes=True` allows Pydantic to read directly from SQLAlchemy models.
    """

    model_config = ConfigDict(from_attributes=True)
