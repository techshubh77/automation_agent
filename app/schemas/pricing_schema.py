from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PricingResult(BaseModel):
    """
    Strongly typed result of a Pricing Engine calculation.

    All monetary fields (USD costs and credits) use Python Decimal to guarantee
    exact financial precision throughout the billing pipeline.
    Tokens remain integers as they are always whole numbers.
    """

    pricing_version: str = Field(
        ...,
        description="The exact pricing matrix version used (e.g., 'pricing_v1'). Never modify versions; create new ones.",
    )
    provider_cost_usd: Decimal = Field(
        ..., description="The raw cost charged by the LLM provider in USD"
    )
    infrastructure_cost_usd: Decimal = Field(
        ..., description="Buffer cost added for infrastructure overhead (Redis, DB, servers)"
    )
    markup_cost_usd: Decimal = Field(
        ..., description="Business profit markup added on top of all costs"
    )
    final_cost_usd: Decimal = Field(
        ..., description="The final total cost in USD billed to the organization"
    )
    credits_used: Decimal = Field(
        ...,
        description="Exact fractional credits consumed. Stored as NUMERIC(18,6) in the database.",
    )
    input_tokens: int = Field(..., description="Number of input/prompt tokens used")
    output_tokens: int = Field(..., description="Number of output/completion tokens used")
    total_tokens: int = Field(..., description="Sum of input and output tokens")

    model_config = ConfigDict(from_attributes=True)
