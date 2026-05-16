"""Provider fallback logic for handling 5xx exhaustion errors."""

import logging
import os
from typing import Optional

from providers.base import ModelResponse, RetryableProviderError
from providers.registry import ModelProviderRegistry

logger = logging.getLogger(__name__)


def generate_with_fallback(
    provider,
    model_name: str,
    **kwargs,
) -> tuple[ModelResponse, Optional[str]]:
    """Call provider.generate_content(); on retryable exhaustion, retry with FALLBACK_MODEL.

    Returns:
        (response, None)         — primary succeeded
        (response, notice_str)   — fallback used; surface notice_str to the user

    Raises:
        RetryableProviderError   — if fallback is disabled, unavailable, or also fails
        RuntimeError             — if the primary raised a non-retryable error (auth, bad request)
    """
    fallback_model = os.getenv("FALLBACK_MODEL", "")

    try:
        return provider.generate_content(model_name=model_name, **kwargs), None
    except RetryableProviderError as primary_err:
        if not fallback_model:
            raise

        if model_name == fallback_model:
            logger.warning(f"Primary model IS the fallback model ({model_name}); not re-trying")
            raise

        fallback_provider = ModelProviderRegistry.get_provider_for_model(fallback_model)
        if fallback_provider is None:
            logger.warning(f"Fallback model '{fallback_model}' has no available provider; giving up")
            raise

        logger.warning(
            f"Primary provider failed after all retries (model={model_name}); " f"falling back to '{fallback_model}'"
        )
        try:
            response = fallback_provider.generate_content(model_name=fallback_model, **kwargs)
            notice = f"Note: Primary provider unavailable, response generated using {fallback_model}"
            return response, notice
        except Exception:
            logger.error(f"Fallback model '{fallback_model}' also failed; re-raising original error")
            raise primary_err
