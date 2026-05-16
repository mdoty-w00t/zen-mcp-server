# Zen MCP Server — Agent Guide

This file documents how to develop, test, and extend the Zen MCP Server for AI coding agents (Codex, Gemini CLI, and others). It covers architecture, conventions, key commands, and environment variables.

---

## What This Project Is

Zen MCP Server is a [Model Context Protocol](https://modelcontextprotocol.com) server that gives AI coding assistants (Claude Code, Gemini CLI, Codex CLI, etc.) access to a fleet of AI models — Gemini, GPT-5, O3, Grok, local Ollama models, and more. Tools like `codereview`, `debug`, `thinkdeep`, and `consensus` orchestrate multi-step workflows across these models within a single conversation thread.

---

## Architecture Overview

```
tools/          MCP tool implementations (one file per tool)
  simple/       Request/response tools (chat, thinkdeep, analyze, …)
    base.py     SimpleTool base class — all simple tools inherit here
  workflow/     Multi-step workflow tools (codereview, debug, precommit, …)
    base.py     WorkflowTool base class
    workflow_mixin.py  BaseWorkflowMixin — expert-analysis orchestration
  consensus.py  Consensus tool (multi-model voting with stance steering)
  shared/
    base_tool.py   BaseTool — root base class for all tools
    base_models.py Pydantic request models

providers/      AI provider implementations
  base.py       ModelProvider ABC, ModelResponse, RetryableProviderError
  registry.py   ModelProviderRegistry — routes model names to providers
  fallback.py   generate_with_fallback() — automatic failover on 5xx errors
  gemini.py     Google Gemini (native API)
  openai_compatible.py  Base for OpenAI, DIAL, XAI, OpenRouter, Custom
  openai_provider.py    OpenAI (GPT-5, O3, O4)
  openrouter.py         OpenRouter aggregator
  custom.py             Local/Ollama/vLLM models
  xai.py                X.AI Grok
  dial.py               DIAL unified enterprise API

systemprompts/  System prompt strings for each tool
config.py       All configuration constants (read from env vars)
server.py       MCP server entry point — registers providers and tools
```

**Call flow for a simple tool request:**
1. `server.py` receives the MCP call, resolves model at the boundary
2. `tools/simple/base.py:SimpleTool.execute()` prepares prompt and calls `generate_with_fallback(provider, model_name, …)`
3. `providers/fallback.py` calls `provider.generate_content()` — on `RetryableProviderError` (5xx exhaustion), retries with `FALLBACK_MODEL` if configured
4. Provider retries up to 4 times internally with delays [1, 3, 5, 8]s before raising

---

## Development Commands

```bash
# Activate virtual environment
source .zen_venv/bin/activate

# Run all quality checks (lint + format + unit tests) — run before every commit
./code_quality_checks.sh

# Run unit tests only
python -m pytest tests/ -v -m "not integration"

# Run a specific test file
python -m pytest tests/test_provider_fallback.py -v

# Run end-to-end simulator tests (requires API keys)
python communication_simulator_test.py --quick          # 6 essential tests
python communication_simulator_test.py --individual <name>   # one test

# List available simulator tests
python communication_simulator_test.py --list-tests

# View server logs
tail -f logs/mcp_server.log
tail -f logs/mcp_activity.log
```

---

## Adding a New Tool

1. Create `tools/mytool.py` inheriting from `SimpleTool` (simple) or `WorkflowTool` (multi-step)
2. Implement `get_name()`, `get_tool_fields()`, `prepare_prompt()`, and `get_system_prompt()`
3. Register it in `server.py` alongside the other tools
4. Add a system prompt string in `systemprompts/`

---

## Adding a New Provider

1. Create `providers/myprovider.py` inheriting `OpenAICompatibleProvider` (if OpenAI-compatible) or `ModelProvider` directly
2. Define `SUPPORTED_MODELS` dict with `ModelCapabilities` entries
3. Implement `generate_content()` — raise `RetryableProviderError` (not `RuntimeError`) when retries are exhausted on a 5xx/network error
4. Register in `providers/registry.py:PROVIDER_PRIORITY_ORDER` and in `server.py`

---

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_MODEL` | `auto` | Default model for all tools. `auto` = Claude picks per task. |
| `FALLBACK_MODEL` | *(empty)* | Model to retry with when the primary exhausts retries on 5xx errors (e.g. `gpt-5`). Empty disables fallback. |
| `DISABLED_TOOLS` | see `.env.example` | Comma-separated tool names to disable |
| `GEMINI_API_KEY` | — | Required for Gemini models |
| `OPENAI_API_KEY` | — | Required for GPT-5, O3, O4 |
| `XAI_API_KEY` | — | Required for Grok models |
| `OPENROUTER_API_KEY` | — | Required for OpenRouter |
| `DIAL_API_KEY` | — | Required for DIAL unified API |
| `CUSTOM_API_URL` | — | Base URL for local models (Ollama/vLLM) |
| `LOCALE` | *(empty)* | Language for AI responses, e.g. `fr-FR` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Copy `.env.example` to `.env` and fill in at least one provider API key before running.

---

## Provider Fallback

When `FALLBACK_MODEL=gpt-5` is set, any tool that fails because the primary provider returned repeated 5xx errors will transparently retry with GPT-5 instead of failing. Auth errors and bad-request errors are not retried.

Implementation: `providers/fallback.py` — `generate_with_fallback(provider, model_name, **kwargs)`.

---

## Testing Conventions

- Unit tests live in `tests/` — plain pytest, no special markers except `@pytest.mark.integration`
- Integration tests (require API keys / Ollama) are tagged `@pytest.mark.integration` and excluded from `./code_quality_checks.sh`
- Provider tests: instantiate provider with `api_key="test-key"` and test logic directly (no real API calls needed for most unit tests)
- Simulator tests in `simulator_tests/` make real API calls — run individually with `--individual`

---

## Code Style

- Formatter: **Black** (auto-applied by `./code_quality_checks.sh`)
- Linter: **Ruff** with auto-fix
- Imports sorted by **isort**
- No comments unless the WHY is non-obvious
- No `hasattr`/`getattr` for attribute access — use proper inheritance hooks
- `RetryableProviderError` (not `RuntimeError`) when a provider exhausts retries on server-side errors
