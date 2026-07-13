from decimal import Decimal

from fastapi import status

from app.config.pricing import PRICING_CONFIG
from app.exceptions.custom_exceptions import AppError
from app.schemas.pricing_schema import PricingResult
from app.utils.logger import logger


class PricingEngine:
    """
    Centralized Credit-Based Pricing Engine.

    Converts LLM token usage into monetary cost, applies business logic
    (infrastructure buffers and markup), and converts to System Credits.

    Design constraints:
    - Pure calculation only. Never writes to the database.
    - All arithmetic uses Python Decimal to prevent floating-point precision errors.
    - Returns a strongly typed PricingResult; never a raw dict.
    - Raises AppError (never silently fails) so callers can handle billing errors explicitly.
    """

    @classmethod
    def calculate(
        cls,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        organization_id: str | None = None,
        reference_id: str | None = None,
    ) -> PricingResult:
        """
        Calculates the complete pricing breakdown for a single AI request.

        Args:
            provider: The LLM provider key (e.g., "openai", "groq"). Must match PRICING_CONFIG.
            model: The specific model name (e.g., "gpt-4o-mini"). Must match PRICING_CONFIG.
            input_tokens: Number of input/prompt tokens reported by the provider.
            output_tokens: Number of output/completion tokens reported by the provider.
            organization_id: Used for structured audit logging only.
            reference_id: Used for structured audit logging only (e.g., conversation ID).

        Returns:
            PricingResult with all monetary fields as Decimal.

        Raises:
            AppError (HTTP 400) if provider/model is unknown in PRICING_CONFIG.
            AppError (HTTP 500) for any unexpected internal calculation error.
        """
        try:
            # 1. Fetch config and pricing matrix
            version = PRICING_CONFIG["version"]
            infra_pct = PRICING_CONFIG["infrastructure_buffer_pct"]
            markup_mult = PRICING_CONFIG["business_markup_multiplier"]

            provider_config = PRICING_CONFIG["providers"].get(provider)
            if not provider_config:
                raise AppError(
                    f"Provider '{provider}' not found in pricing configuration.",
                    status.HTTP_400_BAD_REQUEST,
                )

            model_config = provider_config["models"].get(model)
            if not model_config:
                raise AppError(
                    f"Model '{model}' not found in pricing configuration for provider '{provider}'.",
                    status.HTTP_400_BAD_REQUEST,
                )

            # 2. Calculate Base Provider Cost — all Decimal arithmetic
            # Tokens must be converted via str() to avoid float contamination
            input_tok_d = Decimal(str(input_tokens))
            output_tok_d = Decimal(str(output_tokens))

            input_cost_usd = (input_tok_d / Decimal("1000")) * model_config["input_price_per_1k_usd"]
            output_cost_usd = (output_tok_d / Decimal("1000")) * model_config["output_price_per_1k_usd"]
            base_provider_cost_usd = input_cost_usd + output_cost_usd

            # 3. Add Infrastructure Cost Buffer
            # Example: infra_pct = Decimal("0.30") adds 30% to cover Redis/DB/server costs
            infrastructure_cost_usd = base_provider_cost_usd * infra_pct

            # 4. Apply Business Markup Multiplier
            # markup_mult = Decimal("1.0") means no markup (pass-through pricing for internal tools)
            cost_before_markup = base_provider_cost_usd + infrastructure_cost_usd
            markup_cost_usd = (cost_before_markup * markup_mult) - cost_before_markup
            final_cost_usd = cost_before_markup + markup_cost_usd

            # 5. Convert to System Credits (Decimal result, no rounding)
            # 1 Credit = $0.01 USD. Result is a precise decimal fraction (e.g., 0.015150)
            credit_value_usd = PRICING_CONFIG["credit_value_usd"]
            credits_used = final_cost_usd / credit_value_usd if final_cost_usd > Decimal("0") else Decimal("0")

            # 6. Structured Audit Log — written on every successful calculation
            logger.info(
                "Pricing Calculation | Org: {} | Ref: {} | Provider: {} | Model: {} | "
                "Tokens: {} in / {} out | Cost: ${} | Credits: {} | Version: {}",
                organization_id,
                reference_id,
                provider,
                model,
                input_tokens,
                output_tokens,
                f"{final_cost_usd:.8f}",
                f"{credits_used:.8f}",
                version,
            )

            # 7. Return Strongly Typed Result
            # All monetary values stay as Decimal — no float conversion
            return PricingResult(
                pricing_version=version,
                provider_cost_usd=base_provider_cost_usd,
                infrastructure_cost_usd=infrastructure_cost_usd,
                markup_cost_usd=markup_cost_usd,
                final_cost_usd=final_cost_usd,
                credits_used=credits_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )

        except AppError as e:
            logger.error("PricingEngine config error | Org: {} | {}", organization_id, e.message)
            raise
        except Exception as e:
            logger.error("PricingEngine unexpected failure | Org: {} | {}", organization_id, str(e))
            raise AppError(
                "Internal billing calculation failed", status.HTTP_500_INTERNAL_SERVER_ERROR
            ) from e
