"""
LLM 调度层

设计目标：
- 真实模式：按环境变量调用 Claude / DeepSeek / Ollama。
- Mock 模式：不需要 API Key，不访问外网，可跑完整流水线和测试。
- 所有调用只记录哈希、模型、状态和时间，不把完整 prompt 或 API Key 写入日志。
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from cost_tracker import enrich_record_cost, usage_from_provider, usage_from_text

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency guard
    load_dotenv = None

try:
    import anthropic
except Exception:  # pragma: no cover - optional dependency guard
    anthropic = None

try:
    import openai
except Exception:  # pragma: no cover - optional dependency guard
    openai = None


PROJECT_DIR = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(PROJECT_DIR / ".env")
    # 修复 IDE/sandbox 常注入的"空字符串"覆盖（如 ANTHROPIC_API_KEY=""）。
    # 不用 override=True：那会把运行时设置（如 apply_mock_env 设的 NOVEL_LLM_MODE=mock）也盖掉。
    try:
        from dotenv import dotenv_values
        for _k, _v in (dotenv_values(PROJECT_DIR / ".env") or {}).items():
            if _v and not os.getenv(_k):
                os.environ[_k] = _v
    except Exception:
        pass

MOCK_LITERARY_WARNING = (
    "[Mock 模式：本结果仅验证管道连通，未做文学质量评估。"
    "真实评估必须在 NOVEL_LLM_MODE=real 下运行。]\n\n"
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _middle_clip_text(text: str, limit: int, label: str) -> str:
    if len(text) <= limit:
        return text
    marker = f"\n\n[已压缩：{label}，中间省略 {len(text) - limit} 字]\n\n"
    budget = max(200, limit - len(marker))
    head_len = max(1, budget // 2)
    tail_len = max(1, budget - head_len)
    return f"{text[:head_len].rstrip()}{marker}{text[-tail_len:].lstrip()}"



import functools
import os

def stage_route(workflow_arg_index=None, default_workflow=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            workflow = default_workflow
            if workflow_arg_index is not None and len(args) > workflow_arg_index:
                workflow = args[workflow_arg_index]
            elif "workflow" in kwargs:
                workflow = kwargs["workflow"]
            
            if not workflow:
                workflow = default_workflow or func.__name__

            mapping = {
                'generate_chapter': 'draft',
                'audit_logic': 'audit',
                'check_ai_flavor_local': 'flavor',
                'reader_mirror': 'mirror',
                'deep_check': 'deep',
                'revise_chapter': 'revise',
                'revise_text': 'revise',
                'foreshadowing_extract': 'finalize',
                'character_state_update': 'finalize',
                'scene_plan': 'scene',
                'assist_chapter_outline': 'outline',
                'review_chapter_outline': 'outline',
                'improve_chapter_outline': 'outline',
                'assist_global_outline': 'outline',
                'assist_volume_outline': 'outline',
                'assist_character': 'outline',
                'dramatic-diagnose': 'drama',
                'quality_diagnostics': 'quality',
                'literary-critic': 'literary',
                'style_court': 'style_court',
            }
            stage = mapping.get(workflow)
            if not stage:
                if workflow.startswith('assist_'): stage = 'outline'
                elif workflow.startswith('review_'): stage = 'outline'
                elif workflow.startswith('improve_'): stage = 'outline'
                else: stage = workflow
                
            provider = os.getenv(f"NOVEL_STAGE_{stage.upper()}_PROVIDER")
            model = os.getenv(f"NOVEL_STAGE_{stage.upper()}_MODEL")
            
            old_state = {}
            if provider and model:
                old_state = {
                    "PROSE_PROVIDER": self.PROSE_PROVIDER,
                    "CRITIC_PROVIDER": self.CRITIC_PROVIDER,
                    "REVISE_PROVIDER": self.REVISE_PROVIDER,
                    "ASSIST_PROVIDER": self.ASSIST_PROVIDER,
                    "CLAUDE_MODEL": self.CLAUDE_MODEL,
                    "DEEPSEEK_MODEL": self.DEEPSEEK_MODEL,
                    "OPENROUTER_PROSE_MODEL": self.OPENROUTER_PROSE_MODEL,
                    "OPENROUTER_CRITIC_MODEL": self.OPENROUTER_CRITIC_MODEL,
                    "OPENROUTER_REVISE_MODEL": self.OPENROUTER_REVISE_MODEL,
                    "OPENROUTER_ASSIST_MODEL": self.OPENROUTER_ASSIST_MODEL,
                    "CUSTOM_PROSE_MODEL": self.CUSTOM_PROSE_MODEL,
                    "CUSTOM_CRITIC_MODEL": self.CUSTOM_CRITIC_MODEL,
                    "CUSTOM_REVISE_MODEL": self.CUSTOM_REVISE_MODEL,
                    "CUSTOM_ASSIST_MODEL": self.CUSTOM_ASSIST_MODEL,
                    "CUSTOM_MODEL": self.CUSTOM_MODEL,
                }
                self.PROSE_PROVIDER = provider
                self.CRITIC_PROVIDER = provider
                self.REVISE_PROVIDER = provider
                self.ASSIST_PROVIDER = provider
                self.CLAUDE_MODEL = model
                self.DEEPSEEK_MODEL = model
                self.OPENROUTER_PROSE_MODEL = model
                self.OPENROUTER_CRITIC_MODEL = model
                self.OPENROUTER_REVISE_MODEL = model
                self.OPENROUTER_ASSIST_MODEL = model
                self.CUSTOM_PROSE_MODEL = model
                self.CUSTOM_CRITIC_MODEL = model
                self.CUSTOM_REVISE_MODEL = model
                self.CUSTOM_ASSIST_MODEL = model
                self.CUSTOM_MODEL = model

            try:
                return func(self, *args, **kwargs)
            finally:
                for k, v in old_state.items():
                    setattr(self, k, v)
        return wrapper
    return decorator


class LLMRouter:
    """Role-based LLM gateway with deterministic mock fallbacks."""

    CLAUDE_MODEL = os.getenv("NOVEL_CLAUDE_MODEL", "claude-opus-4-6")
    DEEPSEEK_MODEL = os.getenv("NOVEL_DEEPSEEK_MODEL", "deepseek-v4-pro")
    OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_PROSE_MODEL = os.getenv("NOVEL_OPENROUTER_PROSE_MODEL", "openrouter/auto")
    OPENROUTER_CRITIC_MODEL = os.getenv("NOVEL_OPENROUTER_CRITIC_MODEL", "openrouter/auto")
    OPENROUTER_REVISE_MODEL = os.getenv("NOVEL_OPENROUTER_REVISE_MODEL", "openrouter/auto")
    OPENROUTER_ASSIST_MODEL = os.getenv("NOVEL_OPENROUTER_ASSIST_MODEL", "openrouter/auto")
    CUSTOM_PROVIDER_NAME = os.getenv("NOVEL_CUSTOM_PROVIDER_NAME", "通用接口")
    CUSTOM_BASE_URL = os.getenv("NOVEL_CUSTOM_BASE_URL", "")
    CUSTOM_MODEL = os.getenv("NOVEL_CUSTOM_MODEL", "")
    CUSTOM_PROSE_MODEL = os.getenv("NOVEL_CUSTOM_PROSE_MODEL", os.getenv("NOVEL_CUSTOM_MODEL", ""))
    CUSTOM_CRITIC_MODEL = os.getenv("NOVEL_CUSTOM_CRITIC_MODEL", os.getenv("NOVEL_CUSTOM_MODEL", ""))
    CUSTOM_REVISE_MODEL = os.getenv("NOVEL_CUSTOM_REVISE_MODEL", os.getenv("NOVEL_CUSTOM_MODEL", ""))
    CUSTOM_ASSIST_MODEL = os.getenv("NOVEL_CUSTOM_ASSIST_MODEL", os.getenv("NOVEL_CUSTOM_MODEL", ""))
    OPENAI_TIMEOUT_SECONDS = _env_float("NOVEL_OPENAI_TIMEOUT_SECONDS", _env_float("NOVEL_OPENAI_TIMEOUT", 120.0))
    CUSTOM_RETRY_INPUT_CHAR_LIMIT = _env_int("NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT", 24000)
    CUSTOM_RETRY_MAX_TOKENS = _env_int("NOVEL_CUSTOM_RETRY_MAX_TOKENS", 6000)
    OLLAMA_MODEL = os.getenv("NOVEL_OLLAMA_MODEL", "qwen3:8b")
    OLLAMA_URL = os.getenv("NOVEL_OLLAMA_URL", "http://localhost:11434/api/generate")

    def __init__(self, mode: str | None = None, project_dir: str | Path | None = None):
        self.project_dir = Path(project_dir or PROJECT_DIR)
        self.mode = (mode or os.getenv("NOVEL_LLM_MODE", "auto")).lower()
        self.PROSE_PROVIDER = os.getenv("NOVEL_PROSE_PROVIDER", "anthropic").lower()
        self.CRITIC_PROVIDER = os.getenv("NOVEL_CRITIC_PROVIDER", "deepseek").lower()
        self.REVISE_PROVIDER = os.getenv("NOVEL_REVISE_PROVIDER", "anthropic").lower()
        self.ASSIST_PROVIDER = os.getenv("NOVEL_ASSIST_PROVIDER", "anthropic").lower()
        self.CLAUDE_MODEL = os.getenv("NOVEL_CLAUDE_MODEL", self.CLAUDE_MODEL)
        self.DEEPSEEK_MODEL = os.getenv("NOVEL_DEEPSEEK_MODEL", self.DEEPSEEK_MODEL)
        self.OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", self.OPENROUTER_BASE_URL)
        self.OPENROUTER_PROSE_MODEL = os.getenv("NOVEL_OPENROUTER_PROSE_MODEL", self.OPENROUTER_PROSE_MODEL)
        self.OPENROUTER_CRITIC_MODEL = os.getenv("NOVEL_OPENROUTER_CRITIC_MODEL", self.OPENROUTER_CRITIC_MODEL)
        self.OPENROUTER_REVISE_MODEL = os.getenv("NOVEL_OPENROUTER_REVISE_MODEL", self.OPENROUTER_REVISE_MODEL)
        self.OPENROUTER_ASSIST_MODEL = os.getenv("NOVEL_OPENROUTER_ASSIST_MODEL", self.OPENROUTER_ASSIST_MODEL)
        self.CUSTOM_PROVIDER_NAME = os.getenv("NOVEL_CUSTOM_PROVIDER_NAME", self.CUSTOM_PROVIDER_NAME)
        self.CUSTOM_BASE_URL = os.getenv("NOVEL_CUSTOM_BASE_URL", self.CUSTOM_BASE_URL)
        self.CUSTOM_MODEL = os.getenv("NOVEL_CUSTOM_MODEL", self.CUSTOM_MODEL)
        self.CUSTOM_PROSE_MODEL = os.getenv("NOVEL_CUSTOM_PROSE_MODEL", self.CUSTOM_PROSE_MODEL or self.CUSTOM_MODEL)
        self.CUSTOM_CRITIC_MODEL = os.getenv("NOVEL_CUSTOM_CRITIC_MODEL", self.CUSTOM_CRITIC_MODEL or self.CUSTOM_MODEL)
        self.CUSTOM_REVISE_MODEL = os.getenv("NOVEL_CUSTOM_REVISE_MODEL", self.CUSTOM_REVISE_MODEL or self.CUSTOM_MODEL)
        self.CUSTOM_ASSIST_MODEL = os.getenv("NOVEL_CUSTOM_ASSIST_MODEL", self.CUSTOM_ASSIST_MODEL or self.CUSTOM_MODEL)
        self.OLLAMA_MODEL = os.getenv("NOVEL_OLLAMA_MODEL", self.OLLAMA_MODEL)
        self.OLLAMA_URL = os.getenv("NOVEL_OLLAMA_URL", self.OLLAMA_URL)
        self.CLAUDE_MAX_TOKENS = _env_int("NOVEL_CLAUDE_MAX_TOKENS", 8000)
        self.CLAUDE_TEMPERATURE = _env_float("NOVEL_CLAUDE_TEMPERATURE", 0.85)
        self.DEEPSEEK_MAX_TOKENS = _env_int("NOVEL_DEEPSEEK_MAX_TOKENS", 32000)
        self.DEEPSEEK_REASONING_EFFORT = os.getenv("NOVEL_DEEPSEEK_REASONING_EFFORT", "max")
        self.DEEPSEEK_THINKING = os.getenv("NOVEL_DEEPSEEK_THINKING", "enabled")
        self.OPENAI_TIMEOUT_SECONDS = _env_float("NOVEL_OPENAI_TIMEOUT_SECONDS", _env_float("NOVEL_OPENAI_TIMEOUT", self.OPENAI_TIMEOUT_SECONDS))
        self.CUSTOM_RETRY_INPUT_CHAR_LIMIT = _env_int("NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT", self.CUSTOM_RETRY_INPUT_CHAR_LIMIT)
        self.CUSTOM_RETRY_MAX_TOKENS = _env_int("NOVEL_CUSTOM_RETRY_MAX_TOKENS", self.CUSTOM_RETRY_MAX_TOKENS)
        self.OLLAMA_TIMEOUT = _env_int("NOVEL_OLLAMA_TIMEOUT", 120)
        self.OLLAMA_NUM_PREDICT = _env_int("NOVEL_OLLAMA_NUM_PREDICT", 4096)
        self.OLLAMA_TEMPERATURE = _env_float("NOVEL_OLLAMA_TEMPERATURE", 0.2)
        self.OLLAMA_TOP_P = _env_float("NOVEL_OLLAMA_TOP_P", 0.9)
        self._claude_client: Any | None = None
        self._deepseek_client: Any | None = None
        self._openrouter_client: Any | None = None
        self._custom_client: Any | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @stage_route(default_workflow='generate_chapter')
    def generate_chapter(
        self,
        system_prompt: str,
        context: str,
        chapter_outline: str,
        task_card_text: str = "",
        max_tokens: int | None = None,
    ) -> str:
        if self.mode != "mock" and self.PROSE_PROVIDER not in {"anthropic", "openrouter", "custom", "deepseek"}:
            raise RuntimeError(
                f"NOVEL_PROSE_PROVIDER='{self.PROSE_PROVIDER}' 不支持。"
                "正文生成支持 anthropic / openrouter / custom / deepseek，请检查 .env。"
            )
        user_msg = self._compose_chapter_user_msg(context, chapter_outline, task_card_text)
        payload = f"{system_prompt}\n\n{user_msg}"
        if self.PROSE_PROVIDER == "openrouter":
            if self._should_mock("openrouter", "OPENROUTER_API_KEY"):
                text = self._mock_chapter(chapter_outline, context)
                self._log_call("generate_chapter", "prose_writer", "mock", "mock-prose", payload, "success", output_text=text)
                return text
            return self._openrouter_chat(
                workflow="generate_chapter",
                role="prose_writer",
                model=self.OPENROUTER_PROSE_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                payload=payload,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=self.CLAUDE_TEMPERATURE,
            )
        if self.PROSE_PROVIDER == "custom":
            if self._should_mock("custom", "NOVEL_CUSTOM_API_KEY"):
                text = self._mock_chapter(chapter_outline, context)
                self._log_call("generate_chapter", "prose_writer", "mock", "mock-prose", payload, "success", output_text=text)
                return text
            return self._custom_chat(
                workflow="generate_chapter",
                role="prose_writer",
                model=self._custom_model_for("prose"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                payload=payload,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=self.CLAUDE_TEMPERATURE,
            )
        if self.PROSE_PROVIDER == "deepseek":
            if self._should_mock("deepseek", "DEEPSEEK_API_KEY"):
                text = self._mock_chapter(chapter_outline, context)
                self._log_call("generate_chapter", "prose_writer", "mock", "mock-prose", payload, "success", output_text=text)
                return text
            client = self._get_deepseek_client()
            try:
                response = client.chat.completions.create(
                    model=self.DEEPSEEK_MODEL,
                    max_tokens=max_tokens or self.DEEPSEEK_MAX_TOKENS,
                    reasoning_effort=self.DEEPSEEK_REASONING_EFFORT,
                    extra_body={"thinking": {"type": self.DEEPSEEK_THINKING}},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                )
                text = response.choices[0].message.content
                self._log_call("generate_chapter", "prose_writer", "deepseek", self.DEEPSEEK_MODEL, payload, "success", output_text=text, usage=getattr(response, "usage", None))
                return text
            except Exception as exc:
                self._log_call("generate_chapter", "prose_writer", "deepseek", self.DEEPSEEK_MODEL, payload, "error", str(exc))
                raise

        if self._should_mock("anthropic", "ANTHROPIC_API_KEY"):
            text = self._mock_chapter(chapter_outline, context)
            self._log_call("generate_chapter", "prose_writer", "mock", "mock-prose", payload, "success", output_text=text)
            return text

        try:
            text, usage = self._anthropic_message_text(
                system_prompt=system_prompt,
                user_prompt=user_msg,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=self.CLAUDE_TEMPERATURE,
            )
            self._log_call(
                "generate_chapter", "prose_writer", "anthropic", self.CLAUDE_MODEL, payload, "success", output_text=text, usage=usage
            )
            return text
        except Exception as exc:
            self._log_call(
                "generate_chapter",
                "prose_writer",
                "anthropic",
                self.CLAUDE_MODEL,
                payload,
                "error",
                str(exc),
            )
            raise

    @stage_route(default_workflow='audit_logic')
    def audit_logic(self, chapter_text: str, settings_doc: str = "", recent_summary: str = "") -> str:
        # Auto-inject project axis so auditors always see full constraints (V1.7.2)
        axis = self._axis_context()
        if axis and axis not in settings_doc:
            settings_doc = f"{settings_doc}\n\n{axis}".strip() if settings_doc else axis
        payload = f"{settings_doc}\n\n{recent_summary}\n\n{chapter_text}"
        audit_prompt = self._build_audit_prompt(chapter_text, settings_doc, recent_summary)
        if self.CRITIC_PROVIDER == "openrouter":
            if self._should_mock("openrouter", "OPENROUTER_API_KEY"):
                text = self._mock_audit(chapter_text, settings_doc)
                self._log_call("audit_logic", "critic", "mock", "mock-critic", payload, "success", output_text=text)
                return text
            return self._openrouter_chat(
                workflow="audit_logic",
                role="critic",
                model=self.OPENROUTER_CRITIC_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "你是专业的中文长篇小说逻辑审计员，擅长发现叙事矛盾和设定漏洞。",
                    },
                    {"role": "user", "content": audit_prompt},
                ],
                payload=payload,
                max_tokens=self.DEEPSEEK_MAX_TOKENS,
                temperature=0.2,
            )
        if self.CRITIC_PROVIDER == "custom":
            if self._should_mock("custom", "NOVEL_CUSTOM_API_KEY"):
                text = self._mock_audit(chapter_text, settings_doc)
                self._log_call("audit_logic", "critic", "mock", "mock-critic", payload, "success", output_text=text)
                return text
            return self._custom_chat(
                workflow="audit_logic",
                role="critic",
                model=self._custom_model_for("critic"),
                messages=[
                    {
                        "role": "system",
                        "content": "你是专业的中文长篇小说逻辑审计员，擅长发现叙事矛盾和设定漏洞。",
                    },
                    {"role": "user", "content": audit_prompt},
                ],
                payload=payload,
                max_tokens=self.DEEPSEEK_MAX_TOKENS,
                temperature=0.2,
            )

        if self._should_mock("deepseek", "DEEPSEEK_API_KEY"):
            text = self._mock_audit(chapter_text, settings_doc)
            self._log_call("audit_logic", "critic", "mock", "mock-critic", payload, "success", output_text=text)
            return text

        client = self._get_deepseek_client()
        try:
            response = client.chat.completions.create(
                model=self.DEEPSEEK_MODEL,
                max_tokens=self.DEEPSEEK_MAX_TOKENS,
                reasoning_effort=self.DEEPSEEK_REASONING_EFFORT,
                extra_body={"thinking": {"type": self.DEEPSEEK_THINKING}},
                messages=[
                    {
                        "role": "system",
                        "content": "你是专业的中文长篇小说逻辑审计员，擅长发现叙事矛盾和设定漏洞。",
                    },
                    {"role": "user", "content": audit_prompt},
                ],
            )
            text = response.choices[0].message.content
            self._log_call("audit_logic", "critic", "deepseek", self.DEEPSEEK_MODEL, payload, "success", output_text=text, usage=getattr(response, "usage", None))
            return text
        except Exception as exc:
            self._log_call(
                "audit_logic", "critic", "deepseek", self.DEEPSEEK_MODEL, payload, "error", str(exc)
            )
            raise

    @stage_route(workflow_arg_index=2, default_workflow='critic')
    def critic_text(
        self,
        system_prompt: str,
        user_prompt: str,
        workflow: str = "critic",
        role: str = "critic",
        max_tokens: int | None = None,
    ) -> str:
        """通用 critic 调用，遵从 CRITIC_PROVIDER 设置（默认 DeepSeek）。"""
        payload = f"{system_prompt}\n\n{user_prompt}"
        if self.CRITIC_PROVIDER == "openrouter":
            if self._should_mock("openrouter", "OPENROUTER_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-critic", payload, "success", output_text=text)
                return text
            return self._openrouter_chat(
                workflow=workflow,
                role=role,
                model=self.OPENROUTER_CRITIC_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                payload=payload,
                max_tokens=max_tokens or self.DEEPSEEK_MAX_TOKENS,
                temperature=0.2,
            )
        if self.CRITIC_PROVIDER == "custom":
            if self._should_mock("custom", "NOVEL_CUSTOM_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-critic", payload, "success", output_text=text)
                return text
            return self._custom_chat(
                workflow=workflow,
                role=role,
                model=self._custom_model_for("critic"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                payload=payload,
                max_tokens=max_tokens or self.DEEPSEEK_MAX_TOKENS,
                temperature=0.2,
            )

        if self._should_mock("deepseek", "DEEPSEEK_API_KEY"):
            text = self._mock_assist(user_prompt)
            self._log_call(workflow, role, "mock", "mock-critic", payload, "success", output_text=text)
            return text

        client = self._get_deepseek_client()
        try:
            response = client.chat.completions.create(
                model=self.DEEPSEEK_MODEL,
                max_tokens=max_tokens or self.DEEPSEEK_MAX_TOKENS,
                reasoning_effort=self.DEEPSEEK_REASONING_EFFORT,
                extra_body={"thinking": {"type": self.DEEPSEEK_THINKING}},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = response.choices[0].message.content
            self._log_call(workflow, role, "deepseek", self.DEEPSEEK_MODEL, payload, "success", output_text=text, usage=getattr(response, "usage", None))
            return text
        except Exception as exc:
            self._log_call(workflow, role, "deepseek", self.DEEPSEEK_MODEL, payload, "error", str(exc))
            raise

    @stage_route(workflow_arg_index=2, default_workflow='revise')
    def revise_text(
        self,
        system_prompt: str,
        user_prompt: str,
        workflow: str = "revise",
        role: str = "reviser",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """通用改稿调用，遵从 REVISE_PROVIDER 设置（默认 anthropic）。"""
        payload = f"{system_prompt}\n\n{user_prompt}"
        if self.REVISE_PROVIDER == "openrouter":
            if self._should_mock("openrouter", "OPENROUTER_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-revise", payload, "success", output_text=text)
                return text
            return self._openrouter_chat(
                workflow=workflow,
                role=role,
                model=self.OPENROUTER_REVISE_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                payload=payload,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=temperature if temperature is not None else self.CLAUDE_TEMPERATURE,
            )
        if self.REVISE_PROVIDER == "custom":
            if self._should_mock("custom", "NOVEL_CUSTOM_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-revise", payload, "success", output_text=text)
                return text
            return self._custom_chat(
                workflow=workflow,
                role=role,
                model=self._custom_model_for("revise"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                payload=payload,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=temperature if temperature is not None else self.CLAUDE_TEMPERATURE,
            )
        if self.REVISE_PROVIDER == "deepseek":
            if self._should_mock("deepseek", "DEEPSEEK_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-revise", payload, "success", output_text=text)
                return text
            client = self._get_deepseek_client()
            try:
                response = client.chat.completions.create(
                    model=self.DEEPSEEK_MODEL,
                    max_tokens=max_tokens or self.DEEPSEEK_MAX_TOKENS,
                    reasoning_effort=self.DEEPSEEK_REASONING_EFFORT,
                    extra_body={"thinking": {"type": self.DEEPSEEK_THINKING}},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                text = response.choices[0].message.content
                self._log_call(workflow, role, "deepseek", self.DEEPSEEK_MODEL, payload, "success", output_text=text, usage=getattr(response, "usage", None))
                return text
            except Exception as exc:
                self._log_call(workflow, role, "deepseek", self.DEEPSEEK_MODEL, payload, "error", str(exc))
                raise
        # anthropic (default)
        if self._should_mock("anthropic", "ANTHROPIC_API_KEY"):
            text = self._mock_assist(user_prompt)
            self._log_call(workflow, role, "mock", "mock-revise", payload, "success", output_text=text)
            return text
        try:
            text, usage = self._anthropic_message_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=temperature if temperature is not None else self.CLAUDE_TEMPERATURE,
            )
            self._log_call(workflow, role, "anthropic", self.CLAUDE_MODEL, payload, "success", output_text=text, usage=usage)
            return text
        except Exception as exc:
            self._log_call(workflow, role, "anthropic", self.CLAUDE_MODEL, payload, "error", str(exc))
            raise

    @stage_route(default_workflow='revise_chapter')
    def revise_chapter(
        self,
        system_prompt: str,
        context: str,
        revision_prompt: str,
        task_card_text: str = "",
        max_tokens: int | None = None,
    ) -> str:
        """章节修订调用，遵从 REVISE_PROVIDER 设置。"""
        user_msg = self._compose_chapter_user_msg(context, revision_prompt, task_card_text)
        return self.revise_text(
            system_prompt,
            user_msg,
            workflow="revise_chapter",
            role="reviser",
            max_tokens=max_tokens,
        )

    @stage_route(default_workflow='summary')
    def summarize_local(self, chapter_text: str) -> str:
        payload = chapter_text
        if self.mode == "mock":
            text = self._mock_summary(chapter_text)
            self._log_call("summarize", "local_fallback", "mock", "mock-summary", payload, "success", output_text=text)
            return text

        axis = self._axis_context()
        themes = self._story_themes()
        try:
            template = (self.project_dir / "prompts" / "摘要生成.md").read_text(encoding="utf-8")
            prompt = (
                template
                .replace("{{ project_axis }}", axis)
                .replace("{{ themes }}", themes or "（请从故事规格中提取核心主题，在摘要中注明本章推进了哪些主题）")
                .replace("{{ final_chapter_text }}", chapter_text)
            )
        except Exception:
            axis_block = f"\n\n## 项目轴约束\n{axis}" if axis else ""
            themes_block = f"\n\n## 本章主题呼应\n{themes}" if themes else ""
            prompt = (
                "请为以下小说章节生成一份200字以内的结构化摘要，包含："
                "核心事件、人物状态变化、新伏笔、收回伏笔。"
                "摘要需与项目轴中的故事规格、文风和主线保持一致。"
                f"{axis_block}{themes_block}\n\n"
                f"{chapter_text}"
            )
        try:
            resp = requests.post(
                self.OLLAMA_URL,
                json={
                    "model": self.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": self.OLLAMA_NUM_PREDICT,
                        "temperature": self.OLLAMA_TEMPERATURE,
                        "top_p": self.OLLAMA_TOP_P,
                    },
                },
                timeout=self.OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["response"].strip()
            self._log_call("summarize", "local_fallback", "ollama", self.OLLAMA_MODEL, payload, "success", output_text=text, usage=data)
            return text
        except Exception as exc:
            fallback = self._mock_summary(chapter_text)
            self._log_call(
                "summarize", "local_fallback", "ollama", self.OLLAMA_MODEL, payload, "fallback", str(exc), output_text=fallback
            )
            return fallback

    @stage_route(default_workflow='check_ai_flavor_local')
    def check_ai_flavor_local(self, chapter_text: str, style_context: str = "") -> str:
        style_context = style_context or self._style_check_context()
        payload = f"{style_context}\n\n{chapter_text}" if style_context else chapter_text
        if self.mode == "mock":
            text = self._mock_ai_flavor(chapter_text, style_context)
            self._log_call("ai_flavor", "chinese_polisher", "mock", "mock-ai-flavor", payload, "success", output_text=text)
            return text

        prompt = (
            "请检查以下文本是否存在典型 AI 写作痕迹，并同时核对是否偏离项目文风、故事规格和目标读者期待。"
            "标出疑似段落并给出修改方向：\n"
            "1. 空洞形容词堆砌\n2. 排比过多\n3. 内心独白过直白\n"
            "4. 环境描写与情节无关\n5. 对话过于工整\n"
            "6. 不禁、忍不住、一丝、涌上心头等高频套话\n"
            "7. 与项目文风档案、故事规格、类型卖点不一致\n\n"
            "## 判断参考示例\n"
            "【AI味高——改前】她忍不住感到一丝心痛，泪水悄然涌上心头，内心深处涌起无尽的悲伤与彷徨。\n"
            "【自然——改后】她没说话。窗外的雨打在铁皮屋顶上，她数着滴落的声音，数到第十七下，眼眶才红了。\n\n"
            "【AI味高——改前】他英俊的面庞上写满了坚毅，宽阔的肩膀透露出无尽的力量，令人不禁肃然起敬。\n"
            "【自然——改后】他没有回头。门关上的那一刻，走廊里只剩下他靴子踩过积水的声音。\n\n"
            f"## 项目文风与规格约束\n{style_context or '（未提供，按通用中文小说标准检查）'}\n\n"
            f"{chapter_text}"
        )
        try:
            resp = requests.post(
                self.OLLAMA_URL,
                json={
                    "model": self.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": self.OLLAMA_NUM_PREDICT,
                        "temperature": self.OLLAMA_TEMPERATURE,
                        "top_p": self.OLLAMA_TOP_P,
                    },
                },
                timeout=self.OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["response"].strip()
            self._log_call("ai_flavor", "chinese_polisher", "ollama", self.OLLAMA_MODEL, payload, "success", output_text=text, usage=data)
            return text
        except Exception as exc:
            fallback = self._mock_ai_flavor(chapter_text, style_context)
            self._log_call(
                "ai_flavor", "chinese_polisher", "ollama", self.OLLAMA_MODEL, payload, "fallback", str(exc), output_text=fallback
            )
            return fallback

    # Backward-compatible name used by older WebUI code.
    @stage_route(default_workflow='check_consistency_local')
    def check_consistency_local(self, chapter_text: str) -> str:
        return self.check_ai_flavor_local(chapter_text)

    @stage_route(default_workflow='reader_mirror')
    def reader_mirror(self, chapter_text: str, recent_summary: str = "") -> str:
        """读者镜像：主路径走 CRITIC/DeepSeek，不可用时降级 Ollama 本地。"""
        settings_doc = self._style_check_context()
        prompt = self._build_reader_mirror_prompt(chapter_text, settings_doc, recent_summary)
        payload = f"{settings_doc}\n\n{chapter_text}"

        if self.CRITIC_PROVIDER == "openrouter":
            if self._should_mock("openrouter", "OPENROUTER_API_KEY"):
                return self.check_reader_mirror_local(chapter_text, recent_summary)
            try:
                return self._openrouter_chat(
                    workflow="reader_mirror",
                    role="critic",
                    model=self.OPENROUTER_CRITIC_MODEL,
                    messages=[
                        {"role": "system", "content": "你是专业的长篇小说读者代表，能从目标读者视角审视章节的情感冲击、节奏和追看欲。"},
                        {"role": "user", "content": prompt},
                    ],
                    payload=payload,
                    max_tokens=self.DEEPSEEK_MAX_TOKENS,
                    temperature=0.4,
                )
            except Exception as exc:
                print(f"[reader_mirror] CRITIC/OpenRouter 失败，降级本地：{exc}")
                return self.check_reader_mirror_local(chapter_text, recent_summary)
        if self.CRITIC_PROVIDER == "custom":
            if self._should_mock("custom", "NOVEL_CUSTOM_API_KEY"):
                return self.check_reader_mirror_local(chapter_text, recent_summary)
            try:
                return self._custom_chat(
                    workflow="reader_mirror",
                    role="critic",
                    model=self._custom_model_for("critic"),
                    messages=[
                        {"role": "system", "content": "你是专业的长篇小说读者代表，能从目标读者视角审视章节的情感冲击、节奏和追看欲。"},
                        {"role": "user", "content": prompt},
                    ],
                    payload=payload,
                    max_tokens=self.DEEPSEEK_MAX_TOKENS,
                    temperature=0.4,
                )
            except Exception as exc:
                print(f"[reader_mirror] CRITIC/Custom 失败，降级本地：{exc}")
                return self.check_reader_mirror_local(chapter_text, recent_summary)

        if self._should_mock("deepseek", "DEEPSEEK_API_KEY"):
            return self.check_reader_mirror_local(chapter_text, recent_summary)

        client = self._get_deepseek_client()
        try:
            response = client.chat.completions.create(
                model=self.DEEPSEEK_MODEL,
                max_tokens=self.DEEPSEEK_MAX_TOKENS,
                reasoning_effort=self.DEEPSEEK_REASONING_EFFORT,
                extra_body={"thinking": {"type": self.DEEPSEEK_THINKING}},
                messages=[
                    {"role": "system", "content": "你是专业的长篇小说读者代表，能从目标读者视角审视章节的情感冲击、节奏和追看欲。"},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content.strip()
            self._log_call(
                "reader_mirror", "reader_check", "deepseek", self.DEEPSEEK_MODEL, payload, "success",
                output_text=text, usage=response.usage.model_dump() if hasattr(response, "usage") and response.usage else {},
            )
            return text
        except Exception as exc:
            print(f"[reader_mirror] DeepSeek 失败，降级 Ollama 本地：{exc}")
            self._log_call("reader_mirror", "reader_check", "deepseek", self.DEEPSEEK_MODEL, payload, "fallback", str(exc))
            return self.check_reader_mirror_local(chapter_text, recent_summary)

    def _build_reader_mirror_prompt(self, chapter_text: str, settings_doc: str, recent_summary: str) -> str:
        try:
            template = (self.project_dir / "prompts" / "读者镜像.md").read_text(encoding="utf-8")
            return (
                template
                .replace("{{ project_axis }}", settings_doc)
                .replace("{{ chapter_text }}", chapter_text)
                .replace("{{ recent_summary }}", recent_summary or "（无近期上下文）")
            )
        except Exception:
            return (
                f"请从目标读者视角审视以下章节。\n\n"
                f"## 项目文风与规格约束\n{settings_doc}\n\n"
                f"## 待审章节\n{chapter_text}"
            )

    @stage_route(default_workflow='reader_mirror')
    def check_reader_mirror_local(self, chapter_text: str, recent_summary: str = "") -> str:
        """读者镜像 Ollama 本地降级路径。"""
        settings_doc = self._style_check_context()
        payload = f"{settings_doc}\n\n{chapter_text}"
        if self.mode == "mock":
            text = self._mock_reader_mirror(chapter_text)
            self._log_call("reader_mirror", "reader_check", "mock", "mock-reader-mirror", payload, "success", output_text=text)
            return text

        prompt = self._build_reader_mirror_prompt(chapter_text, settings_doc, recent_summary)
        try:
            resp = requests.post(
                self.OLLAMA_URL,
                json={
                    "model": self.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": self.OLLAMA_NUM_PREDICT,
                        "temperature": 0.4,
                        "top_p": self.OLLAMA_TOP_P,
                    },
                },
                timeout=self.OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["response"].strip()
            self._log_call("reader_mirror", "reader_check", "ollama", self.OLLAMA_MODEL, payload, "success", output_text=text, usage=data)
            return text
        except Exception as exc:
            fallback = self._mock_reader_mirror(chapter_text)
            self._log_call(
                "reader_mirror", "reader_check", "ollama", self.OLLAMA_MODEL, payload, "fallback", str(exc), output_text=fallback
            )
            return fallback

    @stage_route(default_workflow='deep_check')
    def deep_check(self, chapter_text: str, recent_summary: str = "") -> str:
        """深度检查：情感冲击 + 主题推进 + 人物弧光，主路径 CRITIC/DeepSeek。"""
        settings_doc = self._style_check_context()
        prompt = self._build_deep_check_prompt(chapter_text, settings_doc, recent_summary)
        payload = f"{settings_doc}\n\n{chapter_text}"

        if self.mode == "mock":
            text = self._mock_deep_check(chapter_text)
            self._log_call("deep_check", "depth_editor", "mock", "mock-deep-check", payload, "success", output_text=text)
            return text

        if self.CRITIC_PROVIDER == "openrouter":
            if self._should_mock("openrouter", "OPENROUTER_API_KEY"):
                return self._deep_check_local(chapter_text, prompt, payload)
            try:
                return self._openrouter_chat(
                    workflow="deep_check",
                    role="critic",
                    model=self.OPENROUTER_CRITIC_MODEL,
                    messages=[
                        {"role": "system", "content": "你是资深文学编辑，擅长评估小说的情感冲击、主题深度和人物弧光。"},
                        {"role": "user", "content": prompt},
                    ],
                    payload=payload,
                    max_tokens=self.DEEPSEEK_MAX_TOKENS,
                    temperature=0.3,
                )
            except Exception as exc:
                print(f"[deep_check] CRITIC/OpenRouter 失败，降级本地：{exc}")
                return self._deep_check_local(chapter_text, prompt, payload)
        if self.CRITIC_PROVIDER == "custom":
            if self._should_mock("custom", "NOVEL_CUSTOM_API_KEY"):
                return self._deep_check_local(chapter_text, prompt, payload)
            try:
                return self._custom_chat(
                    workflow="deep_check",
                    role="critic",
                    model=self._custom_model_for("critic"),
                    messages=[
                        {"role": "system", "content": "你是资深文学编辑，擅长评估小说的情感冲击、主题深度和人物弧光。"},
                        {"role": "user", "content": prompt},
                    ],
                    payload=payload,
                    max_tokens=self.DEEPSEEK_MAX_TOKENS,
                    temperature=0.3,
                )
            except Exception as exc:
                print(f"[deep_check] CRITIC/Custom 失败，降级本地：{exc}")
                return self._deep_check_local(chapter_text, prompt, payload)

        if self._should_mock("deepseek", "DEEPSEEK_API_KEY"):
            return self._deep_check_local(chapter_text, prompt, payload)

        client = self._get_deepseek_client()
        try:
            response = client.chat.completions.create(
                model=self.DEEPSEEK_MODEL,
                max_tokens=self.DEEPSEEK_MAX_TOKENS,
                reasoning_effort=self.DEEPSEEK_REASONING_EFFORT,
                extra_body={"thinking": {"type": self.DEEPSEEK_THINKING}},
                messages=[
                    {"role": "system", "content": "你是资深文学编辑，擅长评估小说的情感冲击、主题深度和人物弧光。"},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content.strip()
            self._log_call(
                "deep_check", "depth_editor", "deepseek", self.DEEPSEEK_MODEL, payload, "success",
                output_text=text, usage=response.usage.model_dump() if hasattr(response, "usage") and response.usage else {},
            )
            return text
        except Exception as exc:
            print(f"[deep_check] DeepSeek 失败，降级 Ollama 本地：{exc}")
            self._log_call("deep_check", "depth_editor", "deepseek", self.DEEPSEEK_MODEL, payload, "fallback", str(exc))
            return self._deep_check_local(chapter_text, prompt, payload)

    def _build_deep_check_prompt(self, chapter_text: str, settings_doc: str, recent_summary: str) -> str:
        try:
            template = (self.project_dir / "prompts" / "深度检查.md").read_text(encoding="utf-8")
            return (
                template
                .replace("{{ project_axis }}", settings_doc)
                .replace("{{ chapter_text }}", chapter_text)
                .replace("{{ recent_summary }}", recent_summary or "（无近期上下文）")
            )
        except Exception:
            return (
                "请对以下章节做三项深度评估（情感冲击、主题推进、人物弧光）。\n\n"
                f"## 项目文风与规格约束\n{settings_doc}\n\n"
                f"## 待审章节\n{chapter_text}"
            )

    def _deep_check_local(self, chapter_text: str, prompt: str, payload: str) -> str:
        """深度检查 Ollama 本地降级路径。"""
        try:
            resp = requests.post(
                self.OLLAMA_URL,
                json={
                    "model": self.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": self.OLLAMA_NUM_PREDICT,
                        "temperature": 0.3,
                        "top_p": self.OLLAMA_TOP_P,
                    },
                },
                timeout=self.OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["response"].strip()
            self._log_call("deep_check", "depth_editor", "ollama", self.OLLAMA_MODEL, payload, "success", output_text=text, usage=data)
            return text
        except Exception as exc:
            fallback = self._mock_deep_check(chapter_text)
            self._log_call("deep_check", "depth_editor", "ollama", self.OLLAMA_MODEL, payload, "fallback", str(exc), output_text=fallback)
            return fallback

    def _mock_deep_check(self, chapter_text: str) -> str:
        has_climax = any(t in chapter_text[-500:] for t in ["？", "?", "！", "!", "沉默", "怔", "愣", "呆"])
        has_choice = any(t in chapter_text for t in ["选择", "决定", "放弃", "离开", "留下", "转身"])
        return (
            "【情感冲击】" + ("章末有情感锚点，需人工确认力度是否到位。" if has_climax else "建议在章末增加至少一个让读者停顿的瞬间。") + "\n"
            "【主题推进】" + ("本章有人物选择/决定场景，可能推进了核心主题，需人工核实。" if has_choice else "建议加入至少一个不可逆的人物选择来承载主题。") + "\n"
            "【人物弧光】建议检查：主角此刻想要的东西和第一章相比是否在变化？\n"
            "【综合】深度检查为草稿阶段参考；人工朗读标注'最有感觉的段落'和'最想跳过的段落'是最有效的校准。"
        )

    @stage_route(workflow_arg_index=2, default_workflow='assist')
    def assist_text(
        self,
        system_prompt: str,
        user_prompt: str,
        workflow: str = "planning_assist",
        role: str = "director",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """策划辅助调用，遵从 ASSIST_PROVIDER 设置（默认 anthropic）。"""
        payload = f"{system_prompt}\n\n{user_prompt}"
        if self.ASSIST_PROVIDER == "openrouter":
            if self._should_mock("openrouter", "OPENROUTER_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-assist", payload, "success", output_text=text)
                return text
            return self._openrouter_chat(
                workflow=workflow,
                role=role,
                model=self.OPENROUTER_ASSIST_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                payload=payload,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=temperature if temperature is not None else self.CLAUDE_TEMPERATURE,
            )
        if self.ASSIST_PROVIDER == "custom":
            if self._should_mock("custom", "NOVEL_CUSTOM_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-assist", payload, "success", output_text=text)
                return text
            return self._custom_chat(
                workflow=workflow,
                role=role,
                model=self._custom_model_for("assist"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                payload=payload,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=temperature if temperature is not None else self.CLAUDE_TEMPERATURE,
            )
        if self.ASSIST_PROVIDER == "deepseek":
            if self._should_mock("deepseek", "DEEPSEEK_API_KEY"):
                text = self._mock_assist(user_prompt)
                self._log_call(workflow, role, "mock", "mock-assist", payload, "success", output_text=text)
                return text
            client = self._get_deepseek_client()
            try:
                response = client.chat.completions.create(
                    model=self.DEEPSEEK_MODEL,
                    max_tokens=max_tokens or self.DEEPSEEK_MAX_TOKENS,
                    reasoning_effort=self.DEEPSEEK_REASONING_EFFORT,
                    extra_body={"thinking": {"type": self.DEEPSEEK_THINKING}},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                text = response.choices[0].message.content
                self._log_call(workflow, role, "deepseek", self.DEEPSEEK_MODEL, payload, "success", output_text=text, usage=getattr(response, "usage", None))
                return text
            except Exception as exc:
                self._log_call(workflow, role, "deepseek", self.DEEPSEEK_MODEL, payload, "error", str(exc))
                raise
        # anthropic (default)
        if self._should_mock("anthropic", "ANTHROPIC_API_KEY"):
            text = self._mock_assist(user_prompt)
            self._log_call(workflow, role, "mock", "mock-assist", payload, "success", output_text=text)
            return text

        try:
            text, usage = self._anthropic_message_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens or self.CLAUDE_MAX_TOKENS,
                temperature=temperature if temperature is not None else self.CLAUDE_TEMPERATURE,
            )
            self._log_call(workflow, role, "anthropic", self.CLAUDE_MODEL, payload, "success", output_text=text, usage=usage)
            return text
        except Exception as exc:
            self._log_call(workflow, role, "anthropic", self.CLAUDE_MODEL, payload, "error", str(exc))
            raise

    # ------------------------------------------------------------------
    # Clients and mode selection
    # ------------------------------------------------------------------

    def _should_mock(self, provider: str, key_name: str) -> bool:
        if self.mode == "mock":
            return True
        if self.mode == "real":
            return False
        if not os.getenv(key_name):
            return True
        if provider == "anthropic" and anthropic is None:
            return True
        if provider in {"deepseek", "openrouter", "custom"} and openai is None:
            return True
        return False

    def _get_claude_client(self) -> Any:
        if anthropic is None:
            raise RuntimeError("缺少 anthropic 依赖，请安装后再使用真实 Claude 调用。")
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("缺少 ANTHROPIC_API_KEY。可设置 NOVEL_LLM_MODE=mock 跑离线流程。")
        if self._claude_client is None:
            self._claude_client = anthropic.Anthropic(api_key=key)
        return self._claude_client

    def _get_deepseek_client(self) -> Any:
        if openai is None:
            raise RuntimeError("缺少 openai 依赖，请安装后再使用真实 DeepSeek 调用。")
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY。可设置 NOVEL_LLM_MODE=mock 跑离线流程。")
        if self._deepseek_client is None:
            self._deepseek_client = openai.OpenAI(
                api_key=key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                timeout=self.OPENAI_TIMEOUT_SECONDS,
            )
        return self._deepseek_client

    def _get_openrouter_client(self) -> Any:
        if openai is None:
            raise RuntimeError("缺少 openai 依赖，请安装后再使用 OpenRouter 调用。")
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("缺少 OPENROUTER_API_KEY。可设置 NOVEL_LLM_MODE=mock 跑离线流程。")
        if self._openrouter_client is None:
            self._openrouter_client = openai.OpenAI(
                api_key=key,
                base_url=self.OPENROUTER_BASE_URL,
                timeout=self.OPENAI_TIMEOUT_SECONDS,
            )
        return self._openrouter_client

    def _get_custom_client(self) -> Any:
        if openai is None:
            raise RuntimeError("缺少 openai 依赖，请安装后再使用通用接口调用。")
        key = os.getenv("NOVEL_CUSTOM_API_KEY")
        if not key:
            raise RuntimeError("缺少 NOVEL_CUSTOM_API_KEY。可设置 NOVEL_LLM_MODE=mock 跑离线流程。")
        base_url = (self.CUSTOM_BASE_URL or "").strip()
        if not base_url:
            raise RuntimeError("缺少 NOVEL_CUSTOM_BASE_URL。通用接口需提供 OpenAI-compatible base URL。")
        base_url = self._normalize_custom_base_url(base_url)
        if self._custom_client is None:
            self._custom_client = openai.OpenAI(
                api_key=key,
                base_url=base_url.rstrip("/"),
                timeout=self.OPENAI_TIMEOUT_SECONDS,
            )
        return self._custom_client

    def _custom_model_for(self, role: str) -> str:
        models = {
            "prose": self.CUSTOM_PROSE_MODEL,
            "critic": self.CUSTOM_CRITIC_MODEL,
            "revise": self.CUSTOM_REVISE_MODEL,
            "assist": self.CUSTOM_ASSIST_MODEL,
        }
        model = (models.get(role) or self.CUSTOM_MODEL or "").strip()
        if not model:
            raise RuntimeError(f"缺少 NOVEL_CUSTOM_{role.upper()}_MODEL 或 NOVEL_CUSTOM_MODEL。")
        return model

    def _anthropic_message_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, Any | None]:
        client = self._get_claude_client()
        kwargs = {
            "model": self.CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if self._should_stream_anthropic(max_tokens):
            return self._anthropic_stream_text(client, kwargs)
        try:
            response = client.messages.create(**kwargs)
        except ValueError as exc:
            if "Streaming is required" not in str(exc):
                raise
            return self._anthropic_stream_text(client, kwargs)
        return self._message_text(response), getattr(response, "usage", None)

    def _should_stream_anthropic(self, max_tokens: int) -> bool:
        threshold = _env_int("NOVEL_ANTHROPIC_STREAM_THRESHOLD_TOKENS", 20000)
        return max_tokens >= threshold

    def _anthropic_stream_text(self, client: Any, kwargs: dict[str, Any]) -> tuple[str, Any | None]:
        with client.messages.stream(**kwargs) as stream:
            stream.until_done()
            final_message = stream.get_final_message()
            text = stream.get_final_text()
        return text or self._message_text(final_message), getattr(final_message, "usage", None)

    def _message_text(self, response: Any) -> str:
        chunks = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", "")
            if text:
                chunks.append(text)
        return "".join(chunks)

    def _openrouter_chat(
        self,
        workflow: str,
        role: str,
        model: str,
        messages: list[dict[str, str]],
        payload: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        client = self._get_openrouter_client()
        extra_headers = {}
        referer = os.getenv("OPENROUTER_HTTP_REFERER")
        title = os.getenv("OPENROUTER_X_TITLE", "Novel Writing System")
        if referer:
            extra_headers["HTTP-Referer"] = referer
        if title:
            extra_headers["X-Title"] = title
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_headers=extra_headers or None,
            )
            text = self._validate_chat_text(response.choices[0].message.content or "", provider="OpenRouter")
            self._log_call(workflow, role, "openrouter", model, payload, "success", output_text=text, usage=getattr(response, "usage", None))
            return text
        except Exception as exc:
            self._log_call(workflow, role, "openrouter", model, payload, "error", str(exc))
            raise

    def _custom_chat(
        self,
        workflow: str,
        role: str,
        model: str,
        messages: list[dict[str, str]],
        payload: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        client = self._get_custom_client()
        backoffs = [2, 4, 8]  # 5xx 指数退避（共 4 次尝试，最长累计等 14s）
        last_exc: Exception | None = None
        for attempt in range(len(backoffs) + 1):
            try:
                response = self._custom_chat_create(client, model, messages, max_tokens, temperature)
                text = self._validate_chat_text(self._chat_response_text(response), provider=self.CUSTOM_PROVIDER_NAME)
                self._log_call(workflow, role, "custom", model, payload, "success", output_text=text, usage=getattr(response, "usage", None))
                return text
            except Exception as exc:
                last_exc = exc
                # gateway timeout / blocked 通常源于上下文过长或 WAF 规则——
                # 直接跳出走 compact retry，比单纯退避重试更可能成功。
                if self._is_custom_gateway_timeout(exc) or self._is_custom_blocked_error(exc):
                    break
                if attempt < len(backoffs) and self._is_custom_5xx_error(exc):
                    time.sleep(backoffs[attempt])
                    continue
                break

        exc = last_exc
        if self._should_retry_custom_chat(exc, workflow, messages):
            retry_messages = self._compact_custom_retry_messages(messages)
            retry_max_tokens = max(1200, min(max_tokens, self.CUSTOM_RETRY_MAX_TOKENS))
            retry_payload = payload + "\n\n[custom_retry=compact]"
            try:
                response = self._custom_chat_create(client, model, retry_messages, retry_max_tokens, temperature)
                text = self._validate_chat_text(self._chat_response_text(response), provider=self.CUSTOM_PROVIDER_NAME)
                self._log_call(
                    workflow,
                    role,
                    "custom",
                    model,
                    retry_payload,
                    "success",
                    output_text=text,
                    usage=getattr(response, "usage", None),
                )
                return text
            except Exception as retry_exc:
                error_text = self._custom_error_message(retry_exc, retried=True)
                self._log_call(workflow, role, "custom", model, retry_payload, "error", error_text)
                raise RuntimeError(error_text) from retry_exc
        error_text = self._custom_error_message(exc)
        self._log_call(workflow, role, "custom", model, payload, "error", error_text)
        if error_text != str(exc):
            raise RuntimeError(error_text) from exc
        raise exc

    def _custom_chat_create(
        self,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> Any:
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _should_retry_custom_chat(self, exc: Exception, workflow: str, messages: list[dict[str, str]]) -> bool:
        if not workflow.startswith(("generate_", "assist_", "revise_", "scene_")):
            return False
        if sum(len(str(item.get("content", ""))) for item in messages) < self.CUSTOM_RETRY_INPUT_CHAR_LIMIT:
            return False
        return self._is_custom_gateway_timeout(exc) or self._is_custom_blocked_error(exc)

    def _compact_custom_retry_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        limit = max(8000, int(self.CUSTOM_RETRY_INPUT_CHAR_LIMIT))
        fixed_overhead = sum(len(str(item.get("content", ""))) for item in messages[:-1])
        last_budget = max(4000, limit - fixed_overhead)
        compacted: list[dict[str, str]] = []
        for index, item in enumerate(messages):
            role = str(item.get("role", "user"))
            content = str(item.get("content", ""))
            if index == len(messages) - 1 and len(content) > last_budget:
                content = _middle_clip_text(content, last_budget, "通用接口自动压缩重试")
            compacted.append({"role": role, "content": content})
        if compacted:
            compacted[-1]["content"] += (
                "\n\n【系统提示】上文为了避开通用接口网关超时/拦截已自动压缩。"
                "请优先依据章纲、任务卡、当前场景和明确约束完成本次任务，不要解释压缩过程。"
            )
        return compacted

    def _custom_error_message(self, exc: Exception, retried: bool = False) -> str:
        raw = str(exc).strip() or exc.__class__.__name__
        prefix = "压缩重试后仍失败：" if retried else ""
        if self._is_custom_gateway_timeout(exc):
            return (
                f"{prefix}{self.CUSTOM_PROVIDER_NAME} 网关超时。连接测试只发送极短请求，正式创作请求更长；"
                "当前接口在长上下文或长输出时没有及时返回。系统已尝试压缩重试。"
                "建议把“写/策”临时切到 Anthropic/OpenRouter，或把通用接口换成支持长任务/流式转发的 /v1 网关。"
            )
        if self._is_custom_blocked_error(exc):
            return (
                f"{prefix}{self.CUSTOM_PROVIDER_NAME} 拦截了正式创作请求。连接测试成功只代表 API Key 和地址可用，"
                "但长篇正文/策划 prompt 可能触发网站网关的内容过滤或 WAF。系统已尝试压缩重试。"
                "建议换供应商、降低上下文长度，或把该角色路由切到 DeepSeek/OpenRouter。"
            )
        if self._is_timeout_error(exc):
            return (
                f"{prefix}{self.CUSTOM_PROVIDER_NAME} 请求超时（{self.OPENAI_TIMEOUT_SECONDS:g} 秒）。"
                "这通常是长篇策划 prompt 或通用网关响应较慢导致的；"
                "可在设置页调高 NOVEL_OPENAI_TIMEOUT_SECONDS，或把“策/写”切到 Anthropic/OpenRouter 后重试。"
            )
        return raw

    def _is_custom_gateway_timeout(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "error code: 524" in text or "origin_response_timeout" in text or "cloudflare" in text and "timeout" in text

    def _is_custom_5xx_error(self, exc: Exception) -> bool:
        """识别上游 5xx 错误（502/503/504/524 等），用于自动重试。"""
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None) if response is not None else None
        if status is not None:
            try:
                if 500 <= int(status) < 600:
                    return True
            except (TypeError, ValueError):
                pass
        text = str(exc).lower()
        if any(code in text for code in ("error code: 500", "error code: 502", "error code: 503", "error code: 504", "error code: 520", "error code: 521", "error code: 522", "error code: 524")):
            return True
        if any(name in text for name in ("bad gateway", "service unavailable", "gateway timeout", "origin_bad_gateway", "origin_response_timeout", "internalservererror", "internal server error")):
            return True
        return False

    def _is_custom_blocked_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "request was blocked" in text or "access denied" in text or "waf" in text

    def _is_timeout_error(self, exc: Exception) -> bool:
        if openai is not None:
            timeout_error = getattr(openai, "APITimeoutError", None)
            if timeout_error is not None and isinstance(exc, timeout_error):
                return True
        return "timed out" in str(exc).lower() or "timeout" in type(exc).__name__.lower()

    def _chat_response_text(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                first = choices[0] or {}
                message = first.get("message") or {}
                content = message.get("content", "")
                if isinstance(content, list):
                    return "".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in content)
                return str(content or first.get("text") or "")
            return str(response.get("content") or response.get("text") or "")
        choices = getattr(response, "choices", None) or []
        if choices:
            first = choices[0]
            message = getattr(first, "message", None)
            content = getattr(message, "content", None) if message is not None else None
            if isinstance(content, list):
                chunks = []
                for part in content:
                    chunks.append(str(getattr(part, "text", "") or (part.get("text", "") if isinstance(part, dict) else part)))
                return "".join(chunks)
            if content is not None:
                return str(content)
            text = getattr(first, "text", None)
            if text is not None:
                return str(text)
        content = getattr(response, "content", None)
        if content is not None:
            return str(content)
        return str(response)

    def _validate_chat_text(self, text: str, provider: str = "模型接口") -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            raise RuntimeError(f"{provider} 返回了空内容（0 tokens）。请检查模型是否正常响应。")
        if self._looks_like_html_page(cleaned):
            title_match = re.search(r"<title[^>]*>(.*?)</title>", cleaned, flags=re.IGNORECASE | re.DOTALL)
            title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""
            hint = f"（页面标题：{title}）" if title else ""
            raise RuntimeError(
                f"{provider} 返回了网页 HTML，而不是 OpenAI-compatible 聊天 JSON/正文{hint}。"
                "请检查 base_url 是否应以 /v1 结尾、API Key 是否正确、以及该地址是否为模型接口而不是网页入口。"
            )
        return cleaned

    def _normalize_custom_base_url(self, base_url: str) -> str:
        value = (base_url or "").strip().rstrip("/")
        if value in {"https://api.n1n.ai", "http://api.n1n.ai"}:
            return f"{value}/v1"
        if value in {"https://letaicode.cn/claude", "http://letaicode.cn/claude"}:
            return f"{value}/v1"
        if value.endswith("/chat/completions"):
            return value[: -len("/chat/completions")].rstrip("/")
        return value

    def _looks_like_html_page(self, text: str) -> bool:
        head = text[:1000].lower()
        return (
            "<!doctype html" in head
            or "<html" in head
            or ("<head" in head and "<body" in head)
            or ("<script" in head and "<div id=" in head)
        )

    # ------------------------------------------------------------------
    # Prompts and mock outputs
    # ------------------------------------------------------------------

    def _compose_chapter_user_msg(self, context: str, chapter_outline: str, task_card_text: str) -> str:
        parts = [context, "---", f"## 写作指令\n\n{chapter_outline}"]
        if task_card_text and task_card_text.strip():
            parts.append(task_card_text.strip())
        parts.append("请根据以上信息撰写本章正文。严格遵守任务卡中的禁止事项与字数目标。")
        return "\n\n".join(parts)

    def _build_audit_prompt(self, chapter_text: str, settings_doc: str, recent_summary: str) -> str:
        try:
            template = (self.project_dir / "prompts" / "逻辑审计.md").read_text(encoding="utf-8")
            prompt = (
                template
                .replace("{{ project_axis }}", settings_doc)
                .replace("{{ recent_summary }}", recent_summary)
                .replace("{{ chapter_text }}", chapter_text)
            )
            return prompt
        except Exception:
            return f"""请作为严苛中文长篇小说编辑，对以下章节进行逻辑审计。

## 检查清单
1. 时间线是否自洽。
2. 角色行为是否符合人设。
3. 地名、人名、术语是否与设定一致。
4. 因果关系是否成立。
5. 能力或规则体系是否崩溃。
6. 伏笔处理是否合理，有无遗漏、过早或重复。
7. 是否存在 AI 写作常见的顺滑空泛问题。

## 已有设定
{settings_doc}

## 近期章节摘要
{recent_summary}

## 待审章节
{chapter_text}

## 输出格式
逐条列出问题。每条包含：
- 【问题位置】
- 【冲突依据】
- 【修改建议】

若无明显问题，输出：本章未发现明显逻辑问题。"""

    def _mock_chapter(self, chapter_outline: str, context: str) -> str:
        title = "未命名章节"
        for line in chapter_outline.splitlines():
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break
        hook = "门外忽然传来三下很轻的敲门声。"
        return (
            MOCK_LITERARY_WARNING +
            f"# {title}\n\n"
            "雨停在凌晨两点。窗缝里还挂着水声，像有人把一串旧钥匙慢慢拖过墙面。\n\n"
            "主角站在桌前，没有立刻碰那只信封。纸面被水汽泡皱，边角却干净得过分，"
            "像刚从某个不该存在的抽屉里取出来。\n\n"
            "“你确定这是给我的？”他问。\n\n"
            "送信的人没有回答，只把伞尖往后收了半寸。地板上留下一小摊水，形状像一枚被压扁的眼睛。\n\n"
            "信封里只有一张照片。照片背面写着一个日期，正好早于失踪案发生的那天。\n\n"
            "他把照片翻回来，终于看清角落里那个人的脸。那不是陌生人。\n\n"
            f"{hook}\n"
        )

    def _mock_audit(self, chapter_text: str, settings_doc: str) -> str:
        issues = []
        if "【" in chapter_text or "在此填写" in settings_doc:
            issues.append(
                "- 【问题位置】文本或设定中仍含占位符。\n"
                "  【冲突依据】占位符会让生成模型补设定，削弱长期一致性。\n"
                "  【修改建议】在正式生成前补完世界观、角色、章纲中的关键字段。"
            )
        if "不禁" in chapter_text or "一丝" in chapter_text or "涌上心头" in chapter_text:
            issues.append(
                "- 【问题位置】出现高频 AI 腔词语。\n"
                "  【冲突依据】项目文风规则明确禁止套话。\n"
                "  【修改建议】改为动作、停顿、物理细节或对白潜台词。"
            )
        if not issues:
            return MOCK_LITERARY_WARNING + "本章未发现明显逻辑问题。\n\n补充建议：正式定稿前仍需人工检查人物动机、伏笔登记和章末钩子。"
        return MOCK_LITERARY_WARNING + "\n\n".join(issues)

    def _mock_summary(self, chapter_text: str) -> str:
        text = " ".join(chapter_text.split())
        snippet = text[:160] + ("..." if len(text) > 160 else "")
        return (
            f"- 核心事件：{snippet}\n"
            "- 人物状态变化：待人工从定稿中确认并细化。\n"
            "- 新伏笔：请对照章纲中的【埋下】项登记。\n"
            "- 收回伏笔：请对照章纲中的【收回】项标记。"
        )

    def _style_check_context(self) -> str:
        try:
            from prompt_assembly import build_axis_context

            return build_axis_context(self.project_dir)
        except Exception:
            print("[警告] 项目轴上下文注入失败（文风检查），降级为本地文风档案", file=sys.stderr)
            style_path = self.project_dir / "00_世界观" / "文风档案.md"
            return style_path.read_text(encoding="utf-8") if style_path.exists() else ""

    def _axis_context(self) -> str:
        try:
            from prompt_assembly import build_axis_context
            return build_axis_context(self.project_dir)
        except Exception:
            print("[警告] 项目轴上下文注入失败（审查），下游可能在无项目约束条件下运行", file=sys.stderr)
            return ""

    def _story_themes(self) -> str:
        """从故事规格中提取核心主题，用于章节摘要的主题追踪。"""
        try:
            from prompt_assembly import parse_story_spec
            spec = parse_story_spec(self.project_dir)
            parts = []
            if spec.get("core_conflict"):
                parts.append(f"- 核心冲突：{spec['core_conflict'][:200]}")
            if spec.get("selling_points"):
                parts.append(f"- 类型卖点：{spec['selling_points'][:200]}")
            if spec.get("success_criteria"):
                parts.append(f"- 成功标准：{spec['success_criteria'][:200]}")
            if parts:
                return "请在摘要中注明本章推进或呼应了以下哪些主题：\n" + "\n".join(parts)
            return ""
        except Exception:
            print("[警告] 故事主题提取失败，章节摘要可能缺少主题追踪上下文", file=sys.stderr)
            return ""

    def _mock_ai_flavor(self, chapter_text: str, style_context: str = "") -> str:
        flags = [kw for kw in ["不禁", "一丝", "涌上心头", "空气仿佛凝固"] if kw in chapter_text]
        if not flags:
            suffix = "已同步参考项目文风档案与故事规格。" if style_context else "未提供项目文风上下文。"
            return f"未发现明显 AI 高频套话。建议继续人工朗读，重点检查对白是否可区分角色。{suffix}"
        return "疑似 AI 写作痕迹：" + "、".join(flags) + "。建议改为具体动作、停顿和未说出口的信息，并对照项目文风档案重写。"

    def _mock_reader_mirror(self, chapter_text: str) -> str:
        has_hook = any(t in chapter_text[-200:] for t in ["？", "?", "！", "!", "忽然", "突然", "未知", "秘密"])
        has_dialogue = "“" in chapter_text or '"' in chapter_text
        return (
            "【追看欲】" + ("章末有悬念钩子，读者会想翻下一章。" if has_hook else "章末收束偏平，建议加一个信息反转或情感冲击。") + "\n"
            "【情感共振】" + ("本章有对话场景，需人工确认情感深度是否到位。" if has_dialogue else "建议增加至少一次让读者'心一紧'的瞬间。") + "\n"
            "【类型卖点】建议人工对照项目故事规格中的卖点清单逐一检查。\n"
            "【节奏体感】建议朗读检查：连续 5 句以上无动作/冲突推进的段落需要压缩。\n"
            "【人物吸引力】若读者无法清晰说出主角此刻的第一目标，则人物驱动力不足。\n"
            "【综合建议】本章作为草稿可进入修订；人工朗读一遍标注'跳读'和'重读'段落是关键。"
        )

    def _mock_assist(self, user_prompt: str) -> str:
        if "人物状态增量" in user_prompt and '"characters"' in user_prompt:
            return json.dumps(
                {
                    "characters": [
                        {
                            "name": "林渊",
                            "location": "旧城档案室外",
                            "physical_state": "疲惫但可行动，右手旧伤被雨水冻得发僵",
                            "emotional_state": "警觉、怀疑，开始重新面对旧案",
                            "known_information": ["旧信来源异常", "照片日期早于旧案发生日"],
                            "possessions": ["异常旧信", "带日期的旧照片"],
                            "goal": "核实旧信和照片背后的证据链",
                            "relationship_changes": ["对档案管理员的信任降低，转为试探"],
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
        if "场景计划" in user_prompt and "JSON 数组" in user_prompt:
            return json.dumps(
                [
                    {
                        "chapter_number": 1,
                        "scene_number": 1,
                        "title": "旧信入局",
                        "pov_character": "主角",
                        "location": "雨夜旧宅",
                        "scene_goal": "用异常来信触发本章行动，并交代主角当前压力。",
                        "conflict": "主角想保持距离，但线索逼迫他重新面对旧案。",
                        "emotional_tone": "压抑、警觉",
                        "required_information": ["信封来源异常", "照片日期异常"],
                        "forbidden_information": ["不要提前揭露幕后真相"],
                        "estimated_words": 1000,
                    },
                    {
                        "chapter_number": 1,
                        "scene_number": 2,
                        "title": "线索反咬",
                        "pov_character": "主角",
                        "location": "旧城档案室",
                        "scene_goal": "让主角验证线索，同时暴露更大的信息缺口。",
                        "conflict": "档案记录与主角记忆互相矛盾。",
                        "emotional_tone": "紧张、怀疑",
                        "required_information": ["档案缺页", "关键角色隐瞒信息"],
                        "forbidden_information": ["不要让主角凭空得知秘密"],
                        "estimated_words": 1400,
                    },
                    {
                        "chapter_number": 1,
                        "scene_number": 3,
                        "title": "章末钩子",
                        "pov_character": "主角",
                        "location": "档案室外走廊",
                        "scene_goal": "用新的危险或发现收束本章，并留下追读钩子。",
                        "conflict": "刚获得的证据立刻引来监视者。",
                        "emotional_tone": "悬疑、收紧",
                        "required_information": ["章末敲门或跟踪信号"],
                        "forbidden_information": ["不要解决核心谜题"],
                        "estimated_words": 900,
                    },
                ],
                ensure_ascii=False,
                indent=2,
            )
        if "识别本章需要登记的伏笔操作" in user_prompt:
            return json.dumps(
                {
                    "planted": ["照片背面出现早于旧案发生日的日期", "送信人避而不答的身份异常"],
                    "resolved": [],
                },
                ensure_ascii=False,
                indent=2,
            )
        if "批量生成" in user_prompt and "角色档案" in user_prompt:
            if "郁时谌" in user_prompt or "来自未来的礼物" in user_prompt:
                return (
                    "# 角色档案：郁时谌\n\n"
                    "## 基础信息\n- 角色定位：46岁银行从业者，未来礼物的第一接收者与风险承担者。\n\n"
                    "## 核心驱动\n- 外在目标：用未来技术修正失败人生并推动产业跃迁。\n- 内在恐惧：害怕自己只是被未来选择的工具。\n\n"
                    "## 关系钩子\n- 与五位成年女性角色形成事业、伦理、情感与利益交织的长期关系网。\n\n"
                    "## 当前状态\n- 正站在普通中年生活与全球科技变局的分界线上。\n\n"
                    "# 角色档案：沈知夏\n\n"
                    "## 基础信息\n- 角色定位：28岁算法伦理研究者，最早质疑未来礼物代价的人。\n\n"
                    "## 核心驱动\n- 外在目标：确认技术跃迁是否会制造不可逆社会伤害。\n- 内在恐惧：被情感牵引而放弃专业判断。\n\n"
                    "## 关系钩子\n- 她既被郁时谌的改变吸引，也不断逼他回答技术与欲望的边界。\n\n"
                    "## 当前状态\n- 准备接近郁时谌，验证他掌握的技术来源。"
                )
            return (
                "# 角色档案：林渊\n\n"
                "## 基础信息\n- 角色定位：旧案调查者\n\n"
                "## 外貌不可变特征\n- 右手虎口有旧伤。\n\n"
                "## 核心驱动\n- 查清父亲留下的旧案。\n\n"
                "## 恐惧\n- 发现自己一直相信的人才是谎言源头。\n\n"
                "## 道德边界\n- 不用无辜者交换真相。\n\n"
                "## 说话方式\n- 短句，先问事实，后问感受。\n\n"
                "## 绝不会说的话\n- “这和我无关。”\n\n"
                "## 标志性动作\n- 紧张时会摩挲旧伤。\n\n"
                "## 秘密\n- 他隐瞒了最后一次见到父亲的时间。\n\n"
                "## 关系钩子\n- 与档案管理员互相试探。\n\n"
                "## 当前状态\n- 被一封旧信拉回旧城。\n\n"
                "# 角色档案：沈砚\n\n"
                "## 基础信息\n- 角色定位：地下档案管理员\n\n"
                "## 外貌不可变特征\n- 总戴一副有裂纹的细框眼镜。\n\n"
                "## 核心驱动\n- 保住档案系统里唯一能证明真相的证据链。\n\n"
                "## 恐惧\n- 真相公开后牵连自己保护的人。\n\n"
                "## 道德边界\n- 可以撒谎，但不伪造证据。\n\n"
                "## 说话方式\n- 温和、留半句，常把答案藏在反问里。\n\n"
                "## 绝不会说的话\n- “我全都告诉你。”\n\n"
                "## 标志性动作\n- 回答前会把眼镜推回鼻梁。\n\n"
                "## 秘密\n- 他曾亲手删掉一份副本。\n\n"
                "## 关系钩子\n- 他知道林渊父亲留下的暗号。\n\n"
                "## 当前状态\n- 暗中观察林渊是否值得交付线索。"
            )
        if "世界观" in user_prompt:
            if "郁时谌" in user_prompt or "来自未来的礼物" in user_prompt or "科幻、言情" in user_prompt:
                return (
                    "# 世界观草案\n\n"
                    "## 项目规格对齐\n"
                    "- 主角：郁时谌，46岁银行从业者，从普通中年困境进入科技跃迁主线。\n"
                    "- 类型：科幻、言情；世界规则必须同时支撑技术伦理、文明尺度和成年人情感关系。\n"
                    "- 核心卖点：来自未来的礼物、逆转人生、全球科技进步、技术代价与情感选择。\n\n"
                    "## 故事背景\n"
                    "- 近未来现实都市。金融系统仍以旧规则运转，但郁时谌意外收到一件来自未来的礼物。"
                    "这件礼物不是万能金手指，而是一组带有使用限制、伦理代价和外部追踪风险的未来技术包。\n"
                    "- 世界舞台从银行、投资机构、实验室、产业园，逐步扩展到国际科技竞争和社会治理层面。\n\n"
                    "## 核心规则\n"
                    "1. 未来礼物只能提供方向、样本或关键节点，不能直接替主角完成商业、科研和情感选择。\n"
                    "2. 每一次技术提前落地都会改变市场、监管、舆论和亲密关系结构，带来连锁代价。\n"
                    "3. 技术越接近文明级突破，越容易触发资本、国家机构、竞争者和亲密关系中的信任危机。\n\n"
                    "## 主要势力\n"
                    "- 传统金融与银行体系：郁时谌的旧生活来源，也是他最初被低估的地方。\n"
                    "- 新兴科技公司与实验室：承接未来礼物的现实转化，制造财富、声望和伦理压力。\n"
                    "- 监管与国际竞争力量：关注技术来源、产业安全和全球格局变化。\n"
                    "- 情感关系网络：五位成年女性角色分别连接资本、科研、媒体、产业和私人生活，使技术选择必须面对人心代价。\n\n"
                    "## 重要地点\n"
                    "- 银行营业部/风控办公室：中年困境和旧秩序的起点。\n"
                    "- 私人实验室：未来礼物被拆解、验证和失控的核心地点。\n"
                    "- 科技发布会与资本路演现场：主角从个人逆袭走向公众视野。\n\n"
                    "## 术语表\n"
                    "- 未来礼物：来自未来的信息/样机/算法组合，带有限制和反噬风险。\n"
                    "- 时间债务：提前使用未来成果后，现实世界必须支付的社会、伦理或情感代价。\n"
                    "- 可信转化链：把未来技术伪装成现实研发过程所需的论文、专利、团队和资金路径。"
                )
            return (
                "# 世界观草案\n\n"
                "## 故事背景\n"
                "- 类型：都市悬疑\n- 核心舞台：雨夜旧城与被遗忘的地下档案系统\n\n"
                "## 核心规则\n"
                "1. 所有秘密都必须留下可追溯的现实线索。\n"
                "2. 角色不能凭空获得信息，必须通过行动、误解或交换取得。\n\n"
                "## 冲突源\n"
                "旧案、家族隐瞒、城市更新工程之间互相牵连。"
            )
        if "角色" in user_prompt:
            return (
                "# 角色档案：待命名\n\n"
                "## 基础信息\n- 角色定位：关键调查者\n\n"
                "## 核心驱动\n- 外在目标：查清一桩旧案\n- 内在恐惧：再次被重要的人抛下\n\n"
                "## 说话方式\n- 短句，回避直接表达脆弱。"
            )
        if "章纲" in user_prompt:
            return (
                "# 第001章：雨夜来信\n\n"
                "## 基本信息\n- 视角人物：主角\n- 字数目标：3000-4000字\n\n"
                "## 核心事件\n主角收到一封指向旧案的信，被迫重新接触过去。\n\n"
                "## 章末悬念\n照片背面出现一个不该存在的日期。"
            )
        return (
            "# 大纲草案\n\n"
            "## 一句话概括\n一个被旧案改变命运的人，在城市更新前夜重新挖开被封存的真相。\n\n"
            "## 主线\n调查旧案、逼近真相、付出代价、完成选择。\n\n"
            "## 第一阶段\n主角被线索拉回旧城，发现失踪案并未结束。"
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_call(
        self,
        workflow: str,
        role: str,
        provider: str,
        model: str,
        input_text: str,
        status: str,
        error: str | None = None,
        output_text: str = "",
        usage: Any | None = None,
    ) -> None:
        logs_dir = self.project_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        token_usage = usage_from_provider(usage, input_text, output_text) if usage is not None else usage_from_text(input_text, output_text)
        record = {
            "id": hashlib.sha256(f"{datetime.now(timezone.utc).isoformat()}{workflow}".encode()).hexdigest()[:16],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workflow": workflow,
            "role": role,
            "provider": provider,
            "model": model,
            "input_hash": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
            "input_tokens": token_usage["input_tokens"],
            "output_tokens": token_usage["output_tokens"],
            "total_tokens": token_usage["total_tokens"],
            "input_cache_hit_tokens": token_usage.get("input_cache_hit_tokens", 0),
            "input_cache_miss_tokens": token_usage.get("input_cache_miss_tokens", token_usage["input_tokens"]),
            "token_source": token_usage["token_source"],
            "status": status,
            "error": error,
        }
        enrich_record_cost(record)
        with (logs_dir / "llm_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
