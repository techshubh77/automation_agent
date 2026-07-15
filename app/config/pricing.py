"""
Central Pricing Configuration for the AI Automation Agent.

This matrix defines the exact monetary costs of tokens across different providers.
It also sets the conversion rate between USD and internal System Credits.

1 Credit = $0.01 USD
"""

from decimal import Decimal
from types import MappingProxyType

from app.utils.logger import logger

PRICING_CONFIG = {
    "version": "pricing_v1",

    # How much 1 Credit is worth in USD.
    "credit_value_usd": Decimal("0.01"),

    # Infrastructure cost buffer (0.0 = 0%).
    # Example: 0.30 means adding 30% to the base provider cost to cover Redis/DB/Servers.
    "infrastructure_buffer_pct": Decimal("0.0"),

    # Business markup multiplier (1.0 = 1x = no markup).
    # Example: 2.0 means double the cost (100% profit).
    "business_markup_multiplier": Decimal("1.0"),

    # Provider Models
    "providers": {
        "groq": {
            "models": {
                "llama3-8b-8192": {
                    "input_price_per_1k_usd": Decimal("0.00005"),
                    "output_price_per_1k_usd": Decimal("0.00008"),
                },
                "llama-3.3-70b-versatile": {
                    "input_price_per_1k_usd": Decimal("0.00059"),
                    "output_price_per_1k_usd": Decimal("0.00079"),
                }
            }
        },
        "openai": {
            "models": {
                "gpt-4o": {
                    "input_price_per_1k_usd": Decimal("0.0025"),
                    "output_price_per_1k_usd": Decimal("0.0100"),
                },  
                "gpt-4o-mini": {
                    "input_price_per_1k_usd": Decimal("0.00015"),
                    "output_price_per_1k_usd": Decimal("0.00060"),
                },
                "text-embedding-3-small": {
                    "input_price_per_1k_usd": Decimal("0.00002"),
                       "output_price_per_1k_usd": Decimal("0.00000"), # Embeddings have no output cost
                }
            }
        }
    }
}

def _validate_core_settings():
    version = PRICING_CONFIG.get("version", "")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pricing version must be a non-empty string")
    if not version.startswith("pricing_v"):
        raise ValueError(f"pricing version '{version}' must follow the format 'pricing_vN'")

    if PRICING_CONFIG["credit_value_usd"] <= 0:
        raise ValueError("credit_value_usd must be greater than 0")
    if PRICING_CONFIG["business_markup_multiplier"] < Decimal("1.0"):
        raise ValueError("business_markup_multiplier cannot be less than 1.0")
    if PRICING_CONFIG["infrastructure_buffer_pct"] < Decimal("0.0"):
        raise ValueError("infrastructure_buffer_pct cannot be negative")

def _validate_providers():
    providers = PRICING_CONFIG.get("providers", {})
    if not providers:
        raise ValueError("At least one provider must be configured")

    for provider_name, provider_data in providers.items():
        models = provider_data.get("models", {})
        if not models:
            raise ValueError(f"Provider {provider_name} has no models configured")

        for model_name, model_pricing in models.items():
            if "input_price_per_1k_usd" not in model_pricing or "output_price_per_1k_usd" not in model_pricing:
                raise ValueError(f"Model {model_name} under {provider_name} is missing pricing fields")
            if model_pricing["input_price_per_1k_usd"] < 0 or model_pricing["output_price_per_1k_usd"] < 0:
                raise ValueError(f"Model {model_name} has negative pricing")

def validate_pricing_config():
    """
    Validates the pricing configuration on startup.
    Fails fast if any critical billing settings are invalid.
    This runs before the server accepts any traffic — a bad config is a crash, not a warning.
    """
    _validate_core_settings()
    _validate_providers()

# Run validation immediately on import — fails fast if config is broken
validate_pricing_config()
logger.info("Pricing configuration '{}' successfully loaded and validated.", PRICING_CONFIG["version"])

# Freeze the config after validation to prevent any runtime mutation.
# Any code attempting PRICING_CONFIG["key"] = value will raise a TypeError.
PRICING_CONFIG = MappingProxyType(PRICING_CONFIG)
