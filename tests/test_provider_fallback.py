"""Tests for automatic provider fallback on retryable 5xx errors."""

from unittest.mock import MagicMock, patch

import pytest

from providers.base import ModelResponse, RetryableProviderError
from providers.fallback import generate_with_fallback


def _make_response(content="test response"):
    return ModelResponse(
        content=content,
        usage={"input_tokens": 10, "output_tokens": 20},
        model_name="test-model",
        friendly_name="Test",
        provider=None,
    )


def _make_provider(response=None, raise_exc=None):
    provider = MagicMock()
    if raise_exc is not None:
        provider.generate_content.side_effect = raise_exc
    else:
        provider.generate_content.return_value = response or _make_response()
    return provider


# ── Primary success ────────────────────────────────────────────────────────────


def test_primary_success_returns_response_and_no_notice():
    provider = _make_provider(response=_make_response("hello"))
    response, notice = generate_with_fallback(provider, model_name="gpt-5", prompt="hi")
    assert response.content == "hello"
    assert notice is None
    provider.generate_content.assert_called_once()


# ── FALLBACK_MODEL disabled ────────────────────────────────────────────────────


def test_fallback_disabled_propagates_retryable_error(monkeypatch):
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    provider = _make_provider(raise_exc=RetryableProviderError("502 Bad Gateway"))
    with pytest.raises(RetryableProviderError):
        generate_with_fallback(provider, model_name="gemini-2.5-pro", prompt="hi")


def test_empty_fallback_model_propagates_retryable_error(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "")
    provider = _make_provider(raise_exc=RetryableProviderError("503"))
    with pytest.raises(RetryableProviderError):
        generate_with_fallback(provider, model_name="gemini-2.5-pro", prompt="hi")


# ── Non-retryable errors pass through unchanged ────────────────────────────────


def test_non_retryable_runtime_error_propagates(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-5")
    provider = _make_provider(raise_exc=RuntimeError("401 Unauthorized"))
    with pytest.raises(RuntimeError, match="401 Unauthorized"):
        generate_with_fallback(provider, model_name="gemini-2.5-pro", prompt="hi")


def test_non_retryable_error_does_not_trigger_fallback(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-5")
    provider = _make_provider(raise_exc=RuntimeError("401 Unauthorized"))
    with patch("providers.fallback.ModelProviderRegistry") as mock_registry:
        with pytest.raises(RuntimeError):
            generate_with_fallback(provider, model_name="gemini-2.5-pro", prompt="hi")
        mock_registry.get_provider_for_model.assert_not_called()


# ── Same-model guard ───────────────────────────────────────────────────────────


def test_same_model_guard_propagates_error(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-5")
    provider = _make_provider(raise_exc=RetryableProviderError("502"))
    with pytest.raises(RetryableProviderError):
        generate_with_fallback(provider, model_name="gpt-5", prompt="hi")


# ── Fallback provider not available ───────────────────────────────────────────


def test_fallback_provider_unavailable_propagates_original_error(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-5")
    provider = _make_provider(raise_exc=RetryableProviderError("502"))
    with patch("providers.fallback.ModelProviderRegistry") as mock_registry:
        mock_registry.get_provider_for_model.return_value = None
        with pytest.raises(RetryableProviderError):
            generate_with_fallback(provider, model_name="gemini-2.5-pro", prompt="hi")


# ── Successful fallback ────────────────────────────────────────────────────────


def test_fallback_succeeds_returns_response_and_notice(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-5")
    primary = _make_provider(raise_exc=RetryableProviderError("502 Bad Gateway"))
    fallback_response = _make_response("fallback answer")
    fallback_provider = _make_provider(response=fallback_response)

    with patch("providers.fallback.ModelProviderRegistry") as mock_registry:
        mock_registry.get_provider_for_model.return_value = fallback_provider
        response, notice = generate_with_fallback(primary, model_name="gemini-2.5-pro", prompt="hi")

    assert response.content == "fallback answer"
    assert notice is not None
    assert "gpt-5" in notice
    assert "unavailable" in notice.lower()


def test_fallback_uses_fallback_model_name(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-5")
    primary = _make_provider(raise_exc=RetryableProviderError("502"))
    fallback_provider = _make_provider(response=_make_response())

    with patch("providers.fallback.ModelProviderRegistry") as mock_registry:
        mock_registry.get_provider_for_model.return_value = fallback_provider
        generate_with_fallback(primary, model_name="gemini-2.5-pro", prompt="hi", temperature=0.5)

    # Fallback called with fallback model name, not primary model name
    fallback_provider.generate_content.assert_called_once()
    call_kwargs = fallback_provider.generate_content.call_args.kwargs
    assert call_kwargs["model_name"] == "gpt-5"
    assert call_kwargs["prompt"] == "hi"
    assert call_kwargs["temperature"] == 0.5


# ── Fallback also fails ────────────────────────────────────────────────────────


def test_fallback_failure_reraises_original_error(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-5")
    original_err = RetryableProviderError("502 original")
    primary = _make_provider(raise_exc=original_err)
    fallback_provider = _make_provider(raise_exc=RuntimeError("gpt-5 also down"))

    with patch("providers.fallback.ModelProviderRegistry") as mock_registry:
        mock_registry.get_provider_for_model.return_value = fallback_provider
        with pytest.raises(RetryableProviderError) as exc_info:
            generate_with_fallback(primary, model_name="gemini-2.5-pro", prompt="hi")

    assert exc_info.value is original_err


# ── RetryableProviderError is a RuntimeError ──────────────────────────────────


def test_retryable_provider_error_is_runtime_error():
    err = RetryableProviderError("test")
    assert isinstance(err, RuntimeError)
    assert str(err) == "test"
