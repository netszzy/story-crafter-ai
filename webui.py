"""
小说创作系统 WebUI
启动：streamlit run webui.py
"""

import streamlit as st
import os
import re
import sys
import shutil
import json
import html
import difflib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import requests

from webui_infra.navigation import NAV_ITEMS, direct_page_for, visible_nav_for
from webui_infra.state import init_session_state, is_llm_running, set_llm_running
from webui_infra.background_jobs import start_background_job
from webui_infra.inbox import add_inbox_message, mark_inbox_read, read_inbox, unread_count
from webui_infra.pages.continue_writing import render_continue_writing
from webui_infra.components.scroll_health import render_scroll_health
from dramatic_arc_diagnostics import compute_drama_trends

APP_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = APP_DIR
sys.path.insert(0, str(APP_DIR))
PROVIDER_PING_TIMEOUT_SECONDS = 3

# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _widget_key(*parts: object) -> str:
    raw = "__".join(str(part) for part in parts if part is not None)
    cleaned = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", raw).strip("_")
    return cleaned[:180] or "widget"

def inject_app_css():
    st.markdown(
        """
        <style>
        :root {
            --novel-bg: #f7f5f0;
            --novel-panel: #fffdf8;
            --novel-panel-2: #f0eee7;
            --novel-text: #24211c;
            --novel-muted: #756f64;
            --novel-border: #ded8cc;
            --novel-accent: #2f6f6d;
            --novel-accent-2: #8b5e34;
            --novel-danger: #9f3737;
            --surface-paper: #fdfaf3;
            --surface-bg: var(--novel-bg);
            --surface-card: #ffffff;
            --surface-elevated: var(--novel-panel);
            --text-primary: var(--novel-text);
            --text-secondary: #6b665e;
            --text-muted: var(--novel-muted);
            --text-disabled: #d0c9bf;
            --brand-primary: var(--novel-accent);
            --brand-secondary: var(--novel-accent-2);
            --status-good: #7a9d6a;
            --status-warn: #c9a64a;
            --status-bad: var(--novel-danger);
            --border-subtle: rgba(0,0,0,0.06);
            --border-default: rgba(0,0,0,0.12);
            --sidebar-bg: var(--novel-text);
            --sidebar-text: #f8f4ea;
            --sidebar-border: #3d362d;
            --sidebar-hover: #353025;
            --field-placeholder: #8d8679;
            --surface-subtle: #fbf8f1;
            --surface-selected: #e9f2f0;
            --surface-chip: #faf7ef;
            --surface-warn: #fff7df;
            --surface-good: #eaf6f2;
            --surface-bad: #fff0f0;
            --border-warn: #d8b36c;
            --border-good: #7bb09e;
            --border-bad: #c98282;
            --text-warn: #7b5a1c;
            --text-good: #245f55;
            --hero-end: #ece6da;
        }
        .stApp {
            background: var(--novel-bg);
            color: var(--novel-text);
        }
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        .main .block-container {
            background: var(--novel-bg) !important;
            color: var(--novel-text) !important;
        }
        .main .block-container,
        .main .block-container p,
        .main .block-container li,
        .main .block-container label,
        .main .block-container span,
        .main .block-container h1,
        .main .block-container h2,
        .main .block-container h3,
        .main .block-container h4,
        .main .block-container h5,
        .main .block-container h6,
        [data-testid="stMarkdownContainer"] {
            color: var(--novel-text);
        }
        section[data-testid="stSidebar"] {
            background: var(--sidebar-bg);
            color: var(--sidebar-text);
            border-right: 1px solid var(--sidebar-border);
        }
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] h4,
        section[data-testid="stSidebar"] h5,
        section[data-testid="stSidebar"] h6,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
            color: var(--sidebar-text) !important;
        }
        input,
        textarea,
        [data-baseweb="input"],
        [data-baseweb="textarea"],
        [data-baseweb="select"] > div {
            background: var(--surface-elevated) !important;
            color: var(--novel-text) !important;
            border-color: var(--novel-border) !important;
        }
        input::placeholder,
        textarea::placeholder {
            color: var(--field-placeholder) !important;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label {
            border-radius: 6px;
            padding: 5px 8px;
            margin: 2px 0;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: var(--sidebar-hover);
        }
        div[data-testid="stMetric"] {
            background: var(--novel-panel);
            border: 1px solid var(--novel-border);
            border-radius: 8px;
            padding: 12px 14px;
            box-shadow: 0 1px 2px rgba(30, 25, 18, 0.04);
        }
        div[data-testid="stMetric"] label {
            color: var(--novel-muted);
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"],
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
            color: var(--novel-text) !important;
        }
        .stButton > button {
            border-radius: 6px;
            border: 1px solid var(--novel-border);
            font-weight: 600;
        }
        .stButton > button[kind="primary"] {
            background: var(--novel-accent);
            border-color: var(--novel-accent);
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
            border-bottom: 1px solid var(--novel-border);
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 6px 6px 0 0;
            padding: 8px 12px;
        }
        textarea {
            border-radius: 6px !important;
            font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", sans-serif !important;
            line-height: 1.72 !important;
        }
        .novel-hero {
            background: linear-gradient(135deg, var(--surface-elevated) 0%, var(--hero-end) 100%);
            border: 1px solid var(--novel-border);
            border-radius: 8px;
            padding: 18px 20px;
            margin-bottom: 14px;
        }
        .novel-hero h1 {
            font-size: 28px;
            line-height: 1.25;
            margin: 0 0 6px 0;
            letter-spacing: 0;
            color: var(--novel-text) !important;
        }
        .novel-hero p {
            color: var(--novel-muted) !important;
            margin: 0;
        }
        .novel-card {
            background: var(--novel-panel);
            border: 1px solid var(--novel-border);
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 12px;
        }
        .novel-card h3 {
            font-size: 16px;
            margin: 0 0 8px 0;
            letter-spacing: 0;
            color: var(--novel-text) !important;
        }
        .novel-muted {
            color: var(--novel-muted) !important;
            font-size: 13px;
        }
        .novel-binder-item {
            display: flex;
            justify-content: space-between;
            gap: 8px;
            padding: 7px 9px;
            border-radius: 6px;
            border: 1px solid transparent;
            margin-bottom: 4px;
            background: var(--surface-subtle);
            color: var(--novel-text) !important;
        }
        .novel-binder-item span {
            color: var(--novel-text) !important;
        }
        .novel-binder-item.active {
            border-color: var(--novel-accent);
            background: var(--surface-selected);
        }
        .novel-chip {
            display: inline-block;
            border: 1px solid var(--novel-border);
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 12px;
            color: var(--novel-muted) !important;
            background: var(--surface-chip);
        }
        .novel-chip.warn {
            border-color: var(--border-warn);
            color: var(--text-warn) !important;
            background: var(--surface-warn);
        }
        .novel-chip.good {
            border-color: var(--border-good);
            color: var(--text-good) !important;
            background: var(--surface-good);
        }
        .novel-chip.bad {
            border-color: var(--border-bad);
            color: var(--novel-danger) !important;
            background: var(--surface-bad);
        }
        .novel-reader {
            background: var(--novel-panel);
            border: 1px solid var(--novel-border);
            border-radius: 8px;
            padding: 18px 22px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def set_active_project(project_dir: str | Path):
    """切换当前书籍项目目录，并同步 CLI 流水线模块的全局路径。"""
    global PROJECT_DIR
    PROJECT_DIR = Path(project_dir).resolve()
    try:
        import novel_pipeline

        novel_pipeline.PROJECT_DIR = PROJECT_DIR
    except Exception:
        pass

def read_file(rel: str) -> str:
    p = PROJECT_DIR / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""

def write_file(rel: str, content: str, preserve_existing: bool = True):
    p = PROJECT_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if preserve_existing and p.exists() and rel.startswith(("00_世界观/", "01_大纲/", "02_正文/", "03_滚动记忆/", "04_审核日志/", "05_项目管理/")):
        _archive_project_file(p)
    p.write_text(content, encoding="utf-8")
    return p

def _archive_project_file(path: Path) -> Path:
    version_dir = path.parent / "versions"
    version_dir.mkdir(parents=True, exist_ok=True)
    archived = version_dir / f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
    shutil.copy2(path, archived)
    return archived

def read_env() -> dict:
    data = {}
    paths = [APP_DIR / ".env"]
    active_env = PROJECT_DIR / ".env"
    if active_env != paths[0]:
        paths.append(active_env)
    for env_path in paths:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    key, _, value = line.partition("=")
                    data[key.strip()] = value.strip()
    return data

def write_env(data: dict):
    ordered = [
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "NOVEL_CUSTOM_API_KEY",
        "NOVEL_PROSE_PROVIDER",
        "NOVEL_ASSIST_PROVIDER",
        "NOVEL_REVISE_PROVIDER",
        "NOVEL_CRITIC_PROVIDER",
        "NOVEL_CLAUDE_MODEL",
        "NOVEL_CLAUDE_MAX_TOKENS",
        "NOVEL_CLAUDE_TEMPERATURE",
        "NOVEL_DEEPSEEK_MODEL",
        "NOVEL_DEEPSEEK_MAX_TOKENS",
        "NOVEL_DEEPSEEK_REASONING_EFFORT",
        "NOVEL_DEEPSEEK_THINKING",
        "OPENROUTER_BASE_URL",
        "NOVEL_OPENROUTER_PROSE_MODEL",
        "NOVEL_OPENROUTER_ASSIST_MODEL",
        "NOVEL_OPENROUTER_REVISE_MODEL",
        "NOVEL_OPENROUTER_CRITIC_MODEL",
        "OPENROUTER_HTTP_REFERER",
        "OPENROUTER_X_TITLE",
        "NOVEL_CUSTOM_PROVIDER_NAME",
        "NOVEL_CUSTOM_BASE_URL",
        "NOVEL_CUSTOM_MODEL",
        "NOVEL_CUSTOM_PROSE_MODEL",
        "NOVEL_CUSTOM_ASSIST_MODEL",
        "NOVEL_CUSTOM_REVISE_MODEL",
        "NOVEL_CUSTOM_CRITIC_MODEL",
        "NOVEL_STAGE_OUTLINE_PROVIDER",
        "NOVEL_STAGE_OUTLINE_MODEL",
        "NOVEL_STAGE_TASK_PROVIDER",
        "NOVEL_STAGE_TASK_MODEL",
        "NOVEL_STAGE_SCENE_PROVIDER",
        "NOVEL_STAGE_SCENE_MODEL",
        "NOVEL_STAGE_DRAFT_PROVIDER",
        "NOVEL_STAGE_DRAFT_MODEL",
        "NOVEL_STAGE_AUDIT_PROVIDER",
        "NOVEL_STAGE_AUDIT_MODEL",
        "NOVEL_STAGE_FLAVOR_PROVIDER",
        "NOVEL_STAGE_FLAVOR_MODEL",
        "NOVEL_STAGE_MIRROR_PROVIDER",
        "NOVEL_STAGE_MIRROR_MODEL",
        "NOVEL_STAGE_DEEP_PROVIDER",
        "NOVEL_STAGE_DEEP_MODEL",
        "NOVEL_STAGE_QUALITY_PROVIDER",
        "NOVEL_STAGE_QUALITY_MODEL",
        "NOVEL_STAGE_DRAMA_PROVIDER",
        "NOVEL_STAGE_DRAMA_MODEL",
        "NOVEL_STAGE_REVISE_PROVIDER",
        "NOVEL_STAGE_REVISE_MODEL",
        "NOVEL_STAGE_LITERARY_PROVIDER",
        "NOVEL_STAGE_LITERARY_MODEL",
        "NOVEL_STAGE_STYLE_COURT_PROVIDER",
        "NOVEL_STAGE_STYLE_COURT_MODEL",
        "NOVEL_STAGE_FINALIZE_PROVIDER",
        "NOVEL_STAGE_FINALIZE_MODEL",
        "NOVEL_OLLAMA_MODEL",
        "NOVEL_OLLAMA_URL",
        "NOVEL_OLLAMA_TIMEOUT",
        "NOVEL_OLLAMA_NUM_PREDICT",
        "NOVEL_OLLAMA_TEMPERATURE",
        "NOVEL_OLLAMA_TOP_P",
        "NOVEL_LLM_MODE",
        "NOVEL_RAG_MODE",
        "NOVEL_STYLE_PROFILE",
        "NOVEL_EMBED_MODEL",
        "HF_ENDPOINT",
        "HF_HUB_DISABLE_XET",
    ]
    lines = []
    for key in ordered:
        if key in data:
            lines.append(f"{key}={data[key]}")
    for key in sorted(k for k in data if k not in ordered):
        lines.append(f"{key}={data[key]}")
    target = PROJECT_DIR / ".env"
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target

def normalize_openrouter_model_id(model_id: str, provider: str = "anthropic") -> str:
    value = (model_id or "").strip()
    if not value:
        return value
    if "/" in value:
        return value
    return f"{provider}/{value}"


def _ping_provider(provider: str, key: str, model: str, base_url: str = "", referer: str = "", title: str = "") -> tuple[bool, str]:
    key = (key or "").strip()
    if not key:
        return False, "缺少 API key"
    try:
        if provider == "anthropic":
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model or "claude-opus-4-6",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                },
                timeout=PROVIDER_PING_TIMEOUT_SECONDS,
            )
        elif provider == "deepseek":
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                json={
                    "model": model or "deepseek-v4-pro",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                },
                timeout=PROVIDER_PING_TIMEOUT_SECONDS,
            )
        elif provider == "openrouter":
            headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
            if referer:
                headers["HTTP-Referer"] = referer
            if title:
                headers["X-Title"] = title
            response = requests.post(
                f"{(base_url or 'https://openrouter.ai/api/v1').rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": model or "openrouter/auto",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                },
                timeout=PROVIDER_PING_TIMEOUT_SECONDS,
            )
        elif provider == "custom":
            base_url = normalize_custom_base_url(base_url)
            if not base_url.strip():
                return False, "缺少 Base URL"
            if not model.strip():
                return False, "缺少模型 ID"
            response = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                json={
                    "model": model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                },
                timeout=PROVIDER_PING_TIMEOUT_SECONDS,
            )
        else:
            return False, f"未知 provider：{provider}"
        if response.status_code < 400:
            return True, "OK"
        return False, response.text[:200]
    except Exception as exc:
        return False, str(exc)[:200]


def normalize_custom_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    if value in {"https://api.n1n.ai", "http://api.n1n.ai"}:
        return f"{value}/v1"
    if value in {"https://letaicode.cn/claude", "http://letaicode.cn/claude"}:
        return f"{value}/v1"
    if value.endswith("/chat/completions"):
        return value[: -len("/chat/completions")].rstrip("/")
    return value


def custom_base_url_warning(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    if value in {"https://api.n1n.ai", "http://api.n1n.ai"}:
        return "n1n 的通用接口 Base URL 应填写到 /v1，例如 https://api.n1n.ai/v1。"
    if value in {"https://letaicode.cn/claude", "http://letaicode.cn/claude"}:
        return "LetAiCode 的通用接口 Base URL 应填写到 /claude/v1，例如 https://letaicode.cn/claude/v1。"
    if value.endswith("/chat/completions"):
        return "Base URL 不要包含 /chat/completions，系统会自动拼接。"
    return ""


def _ping_all_providers(
    anthropic_key: str,
    claude_model: str,
    deepseek_key: str,
    deepseek_model: str,
    openrouter_key: str,
    openrouter_model: str,
    openrouter_base_url: str,
    openrouter_referer: str,
    openrouter_title: str,
    custom_key: str,
    custom_model: str,
    custom_base_url: str,
) -> dict[str, tuple[bool, str]]:
    jobs = {
        "anthropic": ("anthropic", anthropic_key, claude_model, "", "", ""),
        "deepseek": ("deepseek", deepseek_key, deepseek_model, "", "", ""),
        "openrouter": (
            "openrouter",
            openrouter_key,
            openrouter_model,
            openrouter_base_url,
            openrouter_referer,
            openrouter_title,
        ),
        "custom": ("custom", custom_key, custom_model, custom_base_url, "", ""),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(_ping_provider, *args) for name, args in jobs.items()}
        return {name: future.result() for name, future in futures.items()}


def _render_provider_status(provider: str, key: str, model: str, *, base_url: str = "", referer: str = "", title: str = "") -> None:
    status_key = f"_provider_ping_{provider}"
    label = {"anthropic": "Anthropic", "deepseek": "DeepSeek", "openrouter": "OpenRouter", "custom": "通用接口"}.get(provider, provider)
    col_name, col_test, col_status = st.columns([4, 1, 1])
    col_name.caption(f"{label} · {model or '未配置模型'}")
    if col_test.button("测试", key=f"test_provider_{provider}", use_container_width=True):
        with st.spinner(f"测试 {label}..."):
            st.session_state[status_key] = _ping_provider(provider, key, model, base_url, referer, title)
    status = st.session_state.get(status_key)
    if status is None:
        col_status.markdown(_status_dot("untested", "未测"), unsafe_allow_html=True)
    elif status[0]:
        col_status.markdown(_status_dot("ok", "通过"), unsafe_allow_html=True)
    else:
        col_status.markdown(_status_dot("bad", "失败"), unsafe_allow_html=True)
        col_status.caption(status[1])


def _status_dot(state: str, label: str) -> str:
    colors = {
        "untested": "var(--novel-muted)",
        "ok": "var(--novel-accent-2)",
        "bad": "var(--novel-danger)",
    }
    color = colors.get(state, "var(--novel-muted)")
    return (
        f'<span style="display:inline-flex;align-items:center;gap:6px;">'
        f'<span aria-hidden="true" style="width:8px;height:8px;border-radius:50%;'
        f'background:{color};display:inline-block;"></span>{html.escape(label)}</span>'
    )

def apply_runtime_mode(mock: bool):
    env = read_env()
    for key, value in env.items():
        if value:
            os.environ[key] = value
    if mock:
        os.environ["NOVEL_LLM_MODE"] = "mock"
        os.environ["NOVEL_RAG_MODE"] = "mock"
    else:
        os.environ["NOVEL_LLM_MODE"] = env.get("NOVEL_LLM_MODE", "auto") or "auto"
        os.environ["NOVEL_RAG_MODE"] = env.get("NOVEL_RAG_MODE", "auto") or "auto"


# ─── UI 锁（防止 LLM 调用期间误操作） ──────────────────────────────────────

def _is_llm_running() -> bool:
    return is_llm_running(st.session_state)

def _set_llm_running(val: bool, message: str = "大模型调用进行中，请等待完成"):
    set_llm_running(st.session_state, val, message)
    if val:
        st.session_state["llm_lock_started_at"] = datetime.now().timestamp()
    else:
        st.session_state.pop("llm_lock_started_at", None)


def _start_llm_background_job(
    name: str,
    target,
    *,
    eta_seconds: int = 90,
    on_success=None,
    on_error=None,
) -> None:
    if _is_llm_running():
        st.warning("已有大模型任务正在运行，请等待完成后再启动新的任务。")
        return
    _set_llm_running(True, name)

    def wrapped(cancel_event):
        if cancel_event.is_set():
            return None
        return target(cancel_event)

    def notify_success(result):
        add_inbox_message(
            PROJECT_DIR,
            _background_success_title(name, result),
            _summarize_background_result(result),
            level="success",
            source="后台任务",
        )

    def notify_error(error: str):
        tail = (error or "").strip().splitlines()[-1] if error else "未知错误"
        add_inbox_message(PROJECT_DIR, f"{name}失败", tail, level="error", source="后台任务")

    def notify_cancelled():
        add_inbox_message(PROJECT_DIR, f"{name}已取消", "任务已收到取消请求。", level="warning", source="后台任务")

    start_background_job(
        st.session_state,
        name,
        wrapped,
        eta_seconds=eta_seconds,
        on_success=on_success,
        on_error=on_error,
        notify_success=notify_success,
        notify_error=notify_error,
        notify_cancelled=notify_cancelled,
    )
    st.toast(f"{name}已在后台开始")


def _summarize_background_result(result) -> str:
    if result is None:
        return "后台任务已结束。"
    if isinstance(result, dict) and isinstance(result.get("messages"), (list, tuple)):
        messages = [str(item).strip() for item in result.get("messages", []) if str(item).strip()]
        if not messages:
            return "后台任务已结束。"
        return "\n".join(f"- {item}" for item in messages)[:480]
    if isinstance(result, (str, int, float)):
        text = str(result).strip()
        return text[:240] if text else "后台任务已结束。"
    if isinstance(result, (list, tuple)):
        return f"返回 {len(result)} 项结果。"
    if isinstance(result, dict):
        keys = "、".join(str(k) for k in list(result.keys())[:6])
        return f"返回结果字段：{keys}" if keys else "后台任务已结束。"
    return "后台任务已结束。"


def _background_success_title(name: str, result) -> str:
    if isinstance(result, dict):
        title = str(result.get("inbox_title") or result.get("title") or "").strip()
        if title:
            return title[:80]
        status = result.get("status")
        if status == "complete":
            return f"{name}已完成"
        if status in {"advanced", "paused"}:
            return f"{name}本轮推进结束"
    return f"{name}已完成"


def _render_llm_progress_banner(message: str):
    safe_message = html.escape(message)
    started_at = float(st.session_state.get("llm_lock_started_at", datetime.now().timestamp()))
    elapsed = max(0, int(datetime.now().timestamp() - started_at))
    st.markdown(
        f"""
        <div id="novel-llm-progress" style="
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 999999;
            height: 4px;
            background: rgba(47,111,109,0.15);
            pointer-events: none;
        ">
          <div style="height:4px;width:72%;max-width:95%;background:var(--brand-primary);"></div>
        </div>
        <div style="
            position: fixed;
            left: 50%;
            bottom: 18px;
            transform: translateX(-50%);
            z-index: 999998;
            background: var(--surface-elevated);
            color: var(--text-primary);
            border: 1px solid rgba(0,0,0,0.10);
            border-radius: 8px;
            padding: 10px 14px;
            box-shadow: 0 10px 36px rgba(0,0,0,0.14);
            font-size: 13px;
        ">
          {safe_message} · 已用 {elapsed}s
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_background_job_banner():
    job = st.session_state.get("active_job")
    if not job:
        return
    status = getattr(job, "status", "")
    if status in {"done", "error", "cancelled"}:
        if status == "done":
            callback = getattr(job, "on_success", None)
            if callback:
                callback(getattr(job, "result", None))
            st.toast(_background_success_title(getattr(job, "name", "后台任务"), getattr(job, "result", None)))
        elif status == "error":
            callback = getattr(job, "on_error", None)
            if callback:
                callback(getattr(job, "error", ""))
            st.toast(f"{getattr(job, 'name', '后台任务')}失败")
            with st.expander(f"{getattr(job, 'name', '后台任务')}错误", expanded=False):
                st.code(getattr(job, "error", ""), language="text")
        elif status == "cancelled":
            st.toast(f"{getattr(job, 'name', '后台任务')}已取消")
        st.session_state.pop("active_job", None)
        _set_llm_running(False)
        return

    ratio = float(getattr(job, "progress_ratio", lambda: 0.0)())
    elapsed = int(getattr(job, "elapsed_seconds", lambda: 0)())
    st.progress(ratio, text=f"{getattr(job, 'name', '后台任务')} · 已用 {elapsed}s")
    if st.button("取消后台任务", key="cancel_active_background_job"):
        getattr(job, "cancel", lambda: None)()
        st.toast("已请求取消后台任务")


def _render_lock_banner():
    _render_background_job_banner()
    if _is_llm_running() and not st.session_state.get("active_job"):
        _set_llm_running(False)
        st.info("已恢复一个遗留的后台锁定状态。若上一轮没有显示结果，请重新运行或点击对应区域的「重新读取审查结果」。")
    if _is_llm_running():
        msg = st.session_state.get("llm_lock_message", "大模型调用进行中，请等待完成")
        _render_llm_progress_banner(msg)
        st.info("大模型正在运行。当前版本已取消全屏锁定，你可以查看其它页面；请避免重复触发同一个任务。")


def _review_cache_path(section: str, target: str) -> "Path":
    from pathlib import Path
    base = Path(PROJECT_DIR)
    cache_dir = base / "AI审查缓存"
    safe = re.sub(r'[<>:"/\\|?*\s]+', "_", target).strip("_")
    return cache_dir / f"{section}_{safe}.md"


def _save_review(section: str, target: str, content: str) -> None:
    p = _review_cache_path(section, target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _load_review(section: str, target: str) -> str:
    p = _review_cache_path(section, target)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _review_cache_mtime(section: str, target: str) -> str:
    p = _review_cache_path(section, target)
    if not p.exists():
        return ""
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _render_review_reload_controls(
    section: str,
    cache_key: str,
    state_key: str,
    label: str,
    key_prefix: str = "review",
) -> str:
    cached = _load_review(section, cache_key)
    mtime = _review_cache_mtime(section, cache_key)
    cols = st.columns([1, 2])
    reload_key = _widget_key(key_prefix, "reload_review", section, cache_key)
    if cols[0].button("重新读取审查结果", use_container_width=True, key=reload_key):
        if cached:
            st.session_state[state_key] = cached
            st.success(f"已读取最近审查报告（{mtime}）。")
        elif _is_llm_running():
            st.info("后台审查还在运行；等它完成后再点这里读取结果。")
        else:
            st.warning("没有找到已保存的审查报告。上一轮可能发生在旧版本流程里，请重新运行一次 AI 审查。")
    if cached:
        cols[1].caption(f"{label}：已保存，可直接生成改稿 · {mtime}")
    elif _is_llm_running():
        cols[1].caption(f"{label}：后台运行中，完成后点左侧按钮读取。")
    else:
        cols[1].caption(f"{label}：暂无可用审查报告。")
    return cached


def _render_editable_review_text(
    section: str,
    cache_key: str,
    state_key: str,
    review_text: str,
    label: str,
    key_prefix: str = "review",
) -> str:
    if not review_text:
        return ""
    edit_key = _widget_key(key_prefix, "editable_review", section, cache_key)
    source_key = f"{edit_key}_source"
    if st.session_state.get(source_key) != review_text:
        st.session_state[edit_key] = review_text
        st.session_state[source_key] = review_text
    with st.expander(f"{label}（可编辑后提交给改稿）", expanded=True):
        edited = st.text_area(
            "审查意见",
            height=360,
            key=edit_key,
            help="这里可以删掉误判、补充你的判断，再点击「根据审查生成改稿」。AI 改稿会使用这份编辑后的意见。",
        )
        save_key = _widget_key(key_prefix, "save_edited_review", section, cache_key)
        if st.button("保存修改到审查缓存", use_container_width=True, key=save_key):
            _save_review(section, cache_key, edited)
            st.session_state[state_key] = edited
            st.session_state[source_key] = edited
            st.success("已保存修改后的审查意见。")
    return st.session_state.get(edit_key, review_text)


def _toast_unread_inbox_messages():
    messages = [msg for msg in read_inbox(PROJECT_DIR, limit=10) if not msg.get("read")]
    seen = set(st.session_state.setdefault("_inbox_toasted_ids", []))
    fresh = [msg for msg in reversed(messages) if str(msg.get("id", "")) not in seen]
    for msg in fresh[-3:]:
        body = str(msg.get("body", "")).strip()
        text = str(msg.get("title", "后台消息"))
        if body:
            text = f"{text}\n{body[:120]}"
        st.toast(text)
        seen.add(str(msg.get("id", "")))
    st.session_state["_inbox_toasted_ids"] = list(seen)[-200:]


if hasattr(st, "fragment"):
    @st.fragment(run_every="5s")
    def _render_inbox_push_channel():
        _toast_unread_inbox_messages()
else:
    def _render_inbox_push_channel():
        _toast_unread_inbox_messages()


def _render_inbox_sidebar():
    count = unread_count(PROJECT_DIR)
    with st.expander(f"站内信（{count} 未读）", expanded=False):
        messages = read_inbox(PROJECT_DIR, limit=20)
        if not messages:
            st.caption("暂无后台消息。")
            return
        col_read, col_refresh = st.columns(2)
        if col_read.button("全部已读", use_container_width=True, key="inbox_mark_all_read"):
            mark_inbox_read(PROJECT_DIR)
            st.rerun()
        if col_refresh.button("刷新", use_container_width=True, key="inbox_refresh"):
            st.rerun()
        for msg in messages[:8]:
            title = str(msg.get("title", "后台消息"))
            created = str(msg.get("created_at", ""))
            body = str(msg.get("body", "")).strip()
            unread = not msg.get("read")
            prefix = "未读 · " if unread else ""
            st.markdown(f"**{prefix}{html.escape(title)}**")
            st.caption(created.replace("T", " "))
            if body:
                st.caption(body[:160])
            if unread and st.button("标为已读", key=f"inbox_read_{msg.get('id')}", use_container_width=True):
                mark_inbox_read(PROJECT_DIR, {str(msg.get("id", ""))})
                st.rerun()

# ─────────────────────────────────────────────────────────────────────────────

def default_mock_enabled() -> bool:
    return read_env().get("NOVEL_LLM_MODE", "auto") == "mock"


def _role_model_label(provider: str, or_model: str, cu_model: str, env: dict) -> str:
    if provider == "openrouter":
        return f"OpenRouter ｜ {or_model}"
    if provider == "deepseek":
        return f"DeepSeek ｜ {env.get('NOVEL_DEEPSEEK_MODEL', 'deepseek-v4-pro')}"
    if provider == "custom":
        label = env.get("NOVEL_CUSTOM_PROVIDER_NAME", "通用接口")
        return f"{label} ｜ {cu_model}"
    return f"Anthropic ｜ {env.get('NOVEL_CLAUDE_MODEL', 'claude-opus-4-6')}"


def prose_model_label(mock: bool) -> str:
    if mock:
        return "Mock 离线模式，不调用外部模型"
    env = read_env()
    cu = env.get("NOVEL_CUSTOM_PROSE_MODEL") or env.get("NOVEL_CUSTOM_MODEL", "未配置模型")
    return _role_model_label(env.get("NOVEL_PROSE_PROVIDER", "anthropic"),
                             env.get("NOVEL_OPENROUTER_PROSE_MODEL", "openrouter/auto"), cu, env)


def assist_model_label(mock: bool) -> str:
    if mock:
        return "Mock 离线模式，不调用外部模型"
    env = read_env()
    cu = env.get("NOVEL_CUSTOM_ASSIST_MODEL") or env.get("NOVEL_CUSTOM_MODEL", "未配置模型")
    return _role_model_label(env.get("NOVEL_ASSIST_PROVIDER", "anthropic"),
                             env.get("NOVEL_OPENROUTER_ASSIST_MODEL", "openrouter/auto"), cu, env)


def critic_model_label(mock: bool) -> str:
    if mock:
        return "Mock 离线模式，不调用外部模型"
    env = read_env()
    cu = env.get("NOVEL_CUSTOM_CRITIC_MODEL") or env.get("NOVEL_CUSTOM_MODEL", "未配置模型")
    return _role_model_label(env.get("NOVEL_CRITIC_PROVIDER", "anthropic"),
                             env.get("NOVEL_OPENROUTER_CRITIC_MODEL", "openrouter/auto"), cu, env)


def revise_model_label(mock: bool) -> str:
    if mock:
        return "Mock 离线模式，不调用外部模型"
    env = read_env()
    cu = env.get("NOVEL_CUSTOM_REVISE_MODEL") or env.get("NOVEL_CUSTOM_MODEL", "未配置模型")
    return _role_model_label(env.get("NOVEL_REVISE_PROVIDER", "anthropic"),
                             env.get("NOVEL_OPENROUTER_REVISE_MODEL", "openrouter/auto"), cu, env)


_ACTION_PROVIDER: dict[str, str] = {
    "generate_volume_outline": "assist",
    "review_volume_outline":   "critic",
    "improve_volume_outline":  "revise",
    "review_outline":          "critic",
    "improve_outline":         "revise",
    "generate_task_card":      "assist",
    "plan_scenes":             "assist",
    "draft_scene":             "prose",
    "assemble_scenes":         "prose",
    "full_pipeline":           "prose",
    "audit":                   "critic",
    "reader_mirror":           "critic",
    "drama_diag":              "critic",
    "literary_critic":         "critic",
    "voice_diag":              "local",
    "editor_memo":             "critic",
    "feedback_revise":         "revise",
    "finalize_memory":         "assist",
}


def action_model_label(action: str, mock: bool) -> str:
    role = _ACTION_PROVIDER.get(action)
    if role == "prose":
        return prose_model_label(mock)
    if role == "assist":
        return assist_model_label(mock)
    if role == "critic":
        return critic_model_label(mock)
    if role == "revise":
        return revise_model_label(mock)
    if role == "local":
        return "Ollama 本地"
    return ""

def latest_chapter_text(ch: str) -> tuple[str, str]:
    for rel in [
        f"02_正文/第{ch}章_定稿.md",
        f"02_正文/第{ch}章_修订稿.md",
        f"02_正文/第{ch}章_草稿.md",
    ]:
        content = read_file(rel)
        if content:
            return rel, content
    return "", ""

def task_card_info(chapter_num: int) -> dict:
    path = PROJECT_DIR / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_task_card.json"
    if not path.exists():
        return {"exists": False, "confirmed": False, "status": "missing", "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"exists": True, "confirmed": False, "status": "invalid", "path": str(path)}
    status = data.get("status", "draft")
    return {
        "exists": True,
        "confirmed": status == "confirmed",
        "status": status,
        "path": str(path),
        "data": data,
    }


def _render_task_card_v5_controls(task_rel: str, ch: str) -> None:
    try:
        data = json.loads(read_file(task_rel) or "{}")
    except json.JSONDecodeError:
        st.warning("任务卡 JSON 暂时无法解析，先修正 JSON 后再编辑章节口径。")
        return
    try:
        from style_profiles import style_profile_options
        profile_options = style_profile_options(PROJECT_DIR)
    except Exception:
        profile_options = {"": "未指定"}
    mode_options = ["plot", "bridge", "interior", "atmosphere", "epilogue"]
    ending_options = ["hook", "cliffhanger", "open", "echo"]
    pacing_options = ["fast", "normal", "slow_burn"]
    profile_keys = list(profile_options.keys())
    current_mode = data.get("chapter_mode", "plot") if data.get("chapter_mode") in mode_options else "plot"
    current_ending = data.get("ending_style", "hook") if data.get("ending_style") in ending_options else "hook"
    current_pacing = data.get("pacing", "normal") if data.get("pacing") in pacing_options else "normal"
    current_profile = data.get("style_profile", "") if data.get("style_profile", "") in profile_keys else ""

    with st.expander("V5.0 章节口径", expanded=False):
        # 说明文字
        explanation_map = {
            "章节模式": "plot=剧情推进（默认阈值）/ bridge=过渡 / interior=内心 / atmosphere=氛围（冲突下限为0）",
            "结尾方式": "hook=收束钩 / cliffhanger=悬念 / open=开放式（不强制钩子）/ echo=余韵",
            "节奏": "fast=快节奏 / normal=常规 / slow_burn=慢燃（保护追读类诊断）",
            "风格档案": "金庸=白描动作 / 王小波=机锋反讽 / 余华=节制诗意（影响套话容忍度）",
        }
        st.caption("这些设定会影响诊断阈值、正文生成 prompt 和套话容忍度。")

        col_mode, col_ending = st.columns(2)
        mode = col_mode.selectbox(
            "章节模式", mode_options, index=mode_options.index(current_mode),
            key=f"v5_mode_{ch}", help=explanation_map["章节模式"],
        )
        ending = col_ending.selectbox(
            "结尾方式", ending_options, index=ending_options.index(current_ending),
            key=f"v5_ending_{ch}", help=explanation_map["结尾方式"],
        )
        col_pacing, col_profile = st.columns(2)
        pacing = col_pacing.selectbox(
            "节奏", pacing_options, index=pacing_options.index(current_pacing),
            key=f"v5_pacing_{ch}", help=explanation_map["节奏"],
        )
        profile = col_profile.selectbox(
            "风格档案", profile_keys,
            index=profile_keys.index(current_profile),
            format_func=lambda key: profile_options.get(key, key or "未指定"),
            key=f"v5_profile_{ch}", help=explanation_map["风格档案"],
        )
        if st.button("保存章节口径", use_container_width=True, key=f"save_v5_task_card_{ch}"):
            data.update({
                "chapter_mode": mode,
                "ending_style": ending,
                "pacing": pacing,
                "style_profile": profile,
            })
            write_file(task_rel, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            st.success("已保存 V5.0 章节口径；后续正文生成、诊断和备忘录会读取这些字段。")
            st.rerun()


PLACEHOLDER_PATTERNS = [
    r"\{在此[^}]*\}",
    r"在此填写",
    r"请替换",
    r"此处为空",
    r"主角名",
    r"章节标题",
    r"故事第X天",
    r"待补充",
]
BRACKET_PLACEHOLDER_TOKENS = ["示例", "角色名", "章节标题", "主角名", "某角色", "填写", "替换", "X", "Y"]

PLACEHOLDER_ALLOWED = {
    "00_世界观/角色档案/角色模板.md",
}

def scan_placeholders(paths: list[str] | None = None) -> list[dict]:
    if paths is None:
        paths = [
            "00_世界观/世界观.md",
            "00_世界观/文风档案.md",
            "01_大纲/总纲.md",
            "03_滚动记忆/伏笔追踪.md",
            "03_滚动记忆/人物状态表.md",
        ]
        paths.extend(f"00_世界观/角色档案/{name}" for name in list_md("00_世界观/角色档案"))
        paths.extend(f"01_大纲/卷纲/{name}" for name in list_md("01_大纲/卷纲"))
        paths.extend(f"01_大纲/章纲/{name}" for name in list_md("01_大纲/章纲"))

    findings = []
    combined = re.compile("|".join(f"({pattern})" for pattern in PLACEHOLDER_PATTERNS))
    for rel in paths:
        if rel in PLACEHOLDER_ALLOWED:
            continue
        content = read_file(rel)
        if not content:
            continue
        for line_no, line in enumerate(content.splitlines(), start=1):
            bracket_hits = re.findall(r"【([^】]{0,40})】", line)
            has_placeholder_bracket = any(
                any(token in hit for token in BRACKET_PLACEHOLDER_TOKENS) for hit in bracket_hits
            )
            if combined.search(line) or has_placeholder_bracket:
                findings.append({
                    "file": rel,
                    "line": line_no,
                    "text": line.strip()[:160],
                })
    return findings

def chapter_state(chapter_num: int) -> dict:
    ch = ch_str(chapter_num)
    from workflow_advisor import chapter_flow

    flow = chapter_flow(PROJECT_DIR, chapter_num)
    artifacts = flow["artifacts"]
    task_card = flow["task_card"]
    state = {
        "outline": bool(read_file(flow["outline_path"]).strip()),
        "task_card": task_card["exists"],
        "task_card_confirmed": task_card["status"] == "confirmed",
        "draft": artifacts["draft"],
        "audit": artifacts["audit"],
        "reader_mirror": artifacts.get("reader_mirror", False),
        "quality_diag": artifacts["quality_diag"],
        "drama_diag": artifacts.get("drama_diag", False),
        "literary": artifacts.get("literary", False),
        "style_court": artifacts.get("style_court", False),
        "voice_diag": artifacts.get("voice_diag", False),
        "editor_memo": artifacts.get("editor_memo", False),
        "revised": artifacts["revised"],
        "final": artifacts["final"],
        "memory_recent": f"## 第{chapter_num}章" in read_file("03_滚动记忆/最近摘要.md"),
        "memory_global": f"auto-chapter-{ch}" in read_file("03_滚动记忆/全局摘要.md"),
        "placeholders": flow["placeholders"],
        "recommendation": flow["recommendation"],
        "flow_steps": flow["steps"],
    }
    state["memory_updated"] = artifacts["memory_updated"]
    return state

def next_action_for_state(state: dict) -> str:
    if state.get("recommendation"):
        return state["recommendation"].get("detail", "")
    if state["placeholders"]:
        return "先补完章纲占位符，再进入生成。"
    if not state["outline"]:
        return "先创建并填写本章章纲。"
    if not state["task_card"]:
        return "先从章纲生成章节任务卡。"
    if not state["task_card_confirmed"]:
        return "先人工确认章节任务卡，再进入正式写作。"
    if not state["draft"]:
        return "运行完整流水线生成草稿。"
    if not state["audit"]:
        return "运行逻辑审计。"
    if not state.get("reader_mirror"):
        return "运行读者镜像（参考层），检查追看欲、情感共振和类型卖点。"
    if not state["quality_diag"]:
        return "运行章节质量诊断，检查节奏、对白、套话和任务卡对齐。"
    if not state.get("literary"):
        return "运行文学批评，保护克制、留白和未说之语。"
    if not state.get("style_court"):
        return "运行风格法庭裁决，把工程指标和文学批评的冲突分流为必改与可争议。"
    if not state.get("voice_diag"):
        return "运行角色声音诊断，检查角色对白指纹是否区分得开。"
    if not state.get("editor_memo"):
        return "生成编辑备忘录（综合所有诊断给出 P0/P1/P2 必改项）。"
    if not state["revised"]:
        return "根据审计结果决定是否生成或人工整理修订稿。"
    if not state["final"]:
        return "保存修订稿为定稿草案，并人工精修。"
    if not state["memory_updated"]:
        return "确认定稿并更新长期记忆。"
    return "本章闭环完成，可以进入下一章。"

def health_checks() -> list[dict]:
    env = read_env()
    checks = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"检查项": name, "状态": "通过" if ok else "需处理", "详情": detail})

    required_paths = [
        "00_世界观/世界观.md",
        "00_世界观/文风档案.md",
        "01_大纲/总纲.md",
        "01_大纲/卷纲",
        "01_大纲/章纲",
        "02_正文",
        "03_滚动记忆/全局摘要.md",
        "03_滚动记忆/最近摘要.md",
        "03_滚动记忆/伏笔追踪.md",
        "03_滚动记忆/人物状态表.md",
        "prompts/正文生成.md",
        "prompts/逻辑审计.md",
        "prompts/摘要生成.md",
    ]
    missing = [p for p in required_paths if not (PROJECT_DIR / p).exists()]
    add("目录与模板", not missing, "完整" if not missing else "缺少：" + "、".join(missing))
    app_required = ["rag_engine.py", "llm_router.py", "novel_pipeline.py", ".env.example"]
    app_missing = [p for p in app_required if not (APP_DIR / p).exists()]
    add("应用代码", not app_missing, "完整" if not app_missing else "缺少：" + "、".join(app_missing))

    placeholders = scan_placeholders()
    add("占位符", not placeholders, "未发现关键占位符" if not placeholders else f"发现 {len(placeholders)} 处待补内容")

    add(".env", (PROJECT_DIR / ".env").exists(), "已存在" if (PROJECT_DIR / ".env").exists() else "未创建，可从 .env.example 复制")
    add("ANTHROPIC_API_KEY", bool(env.get("ANTHROPIC_API_KEY")), "已配置" if env.get("ANTHROPIC_API_KEY") else "未配置，auto/mock 模式仍可跑")
    add("DEEPSEEK_API_KEY", bool(env.get("DEEPSEEK_API_KEY")), "已配置" if env.get("DEEPSEEK_API_KEY") else "未配置，auto/mock 模式仍可跑")
    add("OPENROUTER_API_KEY", bool(env.get("OPENROUTER_API_KEY")), "已配置" if env.get("OPENROUTER_API_KEY") else "未配置，未选择 OpenRouter 时不影响")
    custom_ready = bool(env.get("NOVEL_CUSTOM_API_KEY") and env.get("NOVEL_CUSTOM_BASE_URL") and (env.get("NOVEL_CUSTOM_MODEL") or env.get("NOVEL_CUSTOM_PROSE_MODEL")))
    add("通用接口", custom_ready, "已配置" if custom_ready else "未完整配置，未选择 custom 时不影响")

    try:
        import anthropic  # noqa: F401
        add("Anthropic SDK", True, "可导入，真实 Claude 调用可用")
    except Exception as exc:
        add("Anthropic SDK", False, f"不可导入，auto 会降级 Mock：{exc}")

    try:
        import openai  # noqa: F401
        add("OpenAI SDK", True, "可导入，DeepSeek/OpenRouter/通用接口调用可用")
    except Exception as exc:
        add("OpenAI SDK", False, f"不可导入，DeepSeek/OpenRouter/通用接口会降级 Mock：{exc}")

    try:
        import chromadb  # noqa: F401
        add("ChromaDB", True, "可导入")
    except Exception as exc:
        add("ChromaDB", False, str(exc))

    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        add("Ollama", True, "在线：" + ("、".join(models) if models else "无模型列表"))
    except Exception as exc:
        add("Ollama", False, f"不可用：{exc}")

    try:
        from rag_engine import HashEmbeddingModel
        dim = len(HashEmbeddingModel().encode("健康检查"))
        add("Mock RAG", True, f"hash embedding 维度 {dim}")
    except Exception as exc:
        add("Mock RAG", False, str(exc))

    try:
        from novel_schemas import ChapterMemory, ReviewReport  # noqa: F401
        add("结构化 Schema", True, "Pydantic schema 可导入")
    except Exception as exc:
        add("结构化 Schema", False, str(exc))

    task_cards = list((PROJECT_DIR / "01_大纲" / "章纲").glob("*_task_card.json"))
    confirmed = 0
    for path in task_cards:
        try:
            confirmed += 1 if json.loads(path.read_text(encoding="utf-8")).get("status") == "confirmed" else 0
        except json.JSONDecodeError:
            pass
    add("章节任务卡", bool(task_cards), f"{confirmed}/{len(task_cards)} 已确认" if task_cards else "暂无任务卡")

    return checks

def list_md(rel_dir: str) -> list:
    d = PROJECT_DIR / rel_dir
    if not d.exists():
        return []
    names = [f.name for f in d.glob("*.md")]
    if rel_dir.replace("\\", "/") == "00_世界观/角色档案":
        names = [name for name in names if not _looks_like_non_character_profile_name(name)]
    return sorted(names)


def _looks_like_non_character_profile_name(name: str) -> bool:
    stem = Path(name).stem.strip()
    return stem.startswith("#") or "项目规格对齐" in stem

def safe_character_filename(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", (name or "").strip()).strip(" ._")
    if not value:
        raise ValueError("角色名不能为空")
    if value == "角色模板":
        raise ValueError("不能使用保留名称：角色模板")
    return f"{value}.md"

def rename_character_profile(selected_filename: str, new_name: str, overwrite: bool = False) -> Path:
    old_name = Path(selected_filename).name
    if old_name != selected_filename or old_name == "角色模板.md" or not old_name.lower().endswith(".md"):
        raise ValueError("只能重命名正式角色档案")
    new_filename = safe_character_filename(new_name)
    old_path = PROJECT_DIR / "00_世界观" / "角色档案" / old_name
    new_path = PROJECT_DIR / "00_世界观" / "角色档案" / new_filename
    if not old_path.exists():
        raise FileNotFoundError(f"角色档案不存在：{old_name}")
    if old_path.resolve() == new_path.resolve():
        return old_path
    if new_path.exists() and not overwrite:
        raise FileExistsError(f"目标角色档案已存在：{new_filename}")
    if new_path.exists() and not new_path.is_file():
        raise FileExistsError(f"目标路径不是可覆盖的角色档案：{new_filename}")

    _archive_project_file(old_path)
    text = old_path.read_text(encoding="utf-8")
    updated = _rename_character_heading(text, Path(old_name).stem, Path(new_filename).stem)
    if new_path.exists():
        _archive_project_file(new_path)
    new_path.write_text(updated, encoding="utf-8")
    old_path.unlink()
    return new_path

def delete_character_profile(selected_filename: str, reason: str = "") -> Path:
    filename = Path(selected_filename).name
    if filename != selected_filename or filename == "角色模板.md" or not filename.lower().endswith(".md"):
        raise ValueError("只能删除正式角色档案")
    source = PROJECT_DIR / "00_世界观" / "角色档案" / filename
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"角色档案不存在：{filename}")
    recycle_dir = PROJECT_DIR / "99_回收站" / "角色档案"
    recycle_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = _unique_path(recycle_dir / f"{source.stem}_{stamp}{source.suffix}")
    shutil.move(str(source), str(target))
    if reason.strip():
        target.with_suffix(target.suffix + ".reason.txt").write_text(reason.strip() + "\n", encoding="utf-8")
    return target

def _rename_character_heading(text: str, old_name: str, new_name: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines[index] = f"# {new_name}"
            return "\n".join(lines).rstrip() + "\n"
    return f"# {new_name}\n\n{text.lstrip()}".rstrip() + "\n"

def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成唯一文件名：{path}")

def ch_str(n: int) -> str:
    return f"{n:03d}"

def parse_chapter_num(name: str):
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None

def word_count(text: str) -> int:
    return sum(1 for c in text if "一" <= c <= "鿿")

def chapter_status(num: int) -> str:
    ch = ch_str(num)
    if read_file(f"02_正文/第{ch}章_定稿.md").strip():
        return "已定稿"
    if read_file(f"02_正文/第{ch}章_修订稿.md").strip() or read_file(f"02_正文/第{ch}章_草稿.md").strip():
        return "草稿中"
    return "待创作"

WRITING_ASSIST_MODES = {
    "卡点求助": {
        "route": "assist",
        "workflow": "writing_assist_block",
        "system": "你是资深中文长篇小说写作教练，擅长拆解卡点、补足戏剧张力和给出可直接执行的写作方案。",
        "instruction": "请诊断当前章节的写作卡点，给出3-5条具体处理方案，并提供一段可直接采用的示范文本。",
    },
    "续写建议": {
        "route": "assist",
        "workflow": "writing_assist_continue",
        "system": "你是中文长篇小说续写策划，擅长在不破坏伏笔、人物动机和章节任务卡的前提下推进下一段。",
        "instruction": "请基于当前稿件末尾设计下一段推进方式，输出续写方向、风险提醒和一段示范续写。",
    },
    "润色改写": {
        "route": "revise",
        "workflow": "writing_assist_polish",
        "system": "你是中文长篇小说改稿编辑，擅长保留剧情事实并提升文气、画面、节奏和人物动作的准确度。",
        "instruction": "请对选中片段或当前稿件窗口进行润色改写，保留事实与人物关系，不新增设定，不提前揭露伏笔。",
    },
    "首尾钩子增强": {
        "route": "revise",
        "workflow": "writing_assist_hooks",
        "system": "你是顶级中文类型小说开场与章末编辑，擅长用异常、压力、选择和余味提升读者翻页欲。",
        "instruction": "请只围绕章首抓力与章末余味做增强：章首更快制造问题和角色行动压力，章末留下更清晰的未解信息、反转或情绪余波；保留中段事实，不新增硬设定。",
    },
    "好看度精修": {
        "route": "revise",
        "workflow": "writing_assist_beautify",
        "system": "你是顶级中文类型小说精修编辑，擅长把正确但普通的章节改成更有追读张力、画面质地、潜台词和情绪余味的正文。",
        "instruction": "请依据质量诊断与当前稿件做一轮好看度精修：强化冲突压力、异常线索、身体化情绪、场景物件和章末追读感；保留事实，不新增硬设定。",
    },
    "自定义指令": {
        "route": "assist",
        "workflow": "writing_assist_custom",
        "system": "你是中文长篇小说创作助理，必须严格根据项目轴、章节任务卡和用户指令提供可执行文本。",
        "instruction": "请严格执行用户指令，输出可直接用于当前章节的结果。",
    },
}

ADOPTABLE_ASSIST_HEADINGS = (
    "可直接采用文本",
    "可直接使用文本",
    "可采用文本",
    "示范续写",
    "示范文本",
    "改写稿",
    "润色结果",
    "正文片段",
    "完整章节修订稿",
    "首尾增强稿",
)

def build_writing_assist_prompt(
    chapter_num: int,
    mode: str,
    user_request: str = "",
    selected_text: str = "",
    use_rag: bool = True,
) -> tuple[str, str, str]:
    if mode not in WRITING_ASSIST_MODES:
        raise ValueError(f"未知写作辅助类型：{mode}")
    cfg = WRITING_ASSIST_MODES[mode]
    ch = ch_str(chapter_num)
    outline = read_file(f"01_大纲/章纲/第{ch}章.md")
    source_rel, current_text = latest_chapter_text(ch)
    text_window = _writing_assist_text_window(current_text, selected_text, mode)
    context = _writing_assist_context(outline, use_rag=use_rag)
    quality_context = _writing_assist_quality_context(chapter_num)
    task_card = ""
    try:
        from prompt_assembly import render_task_card_block

        task_card = render_task_card_block(PROJECT_DIR, chapter_num)
    except Exception:
        task_card = read_file(f"01_大纲/章纲/第{ch}章_task_card.json")

    prompt = f"""## 当前任务
{cfg["instruction"]}

## 用户补充指令
{user_request.strip() or "无"}

## 项目与长篇上下文
{context or "无"}

## 本章章纲
{outline or "无"}

## 本章任务卡
{task_card or "无"}

## 当前稿件来源
{source_rel or "暂无正文稿件"}

## 质量诊断与好看度雷达
{quality_context or "暂无质量诊断。必要时先运行质量诊断，再做精修。"}

## 当前处理文本
{text_window or "无"}

## 输出要求
- 不覆盖正文，不宣称已经保存到正文。
- 明确区分“建议”和“可直接采用文本”。
- 若生成正文片段，只输出当前章节可用内容，不写解释性前言。
"""
    return str(cfg["system"]), prompt, str(cfg["route"])

def run_writing_assist(
    chapter_num: int,
    mode: str,
    user_request: str = "",
    selected_text: str = "",
    mock: bool = False,
    llm=None,
    use_rag: bool = True,
) -> Path:
    apply_runtime_mode(mock)
    from llm_router import LLMRouter

    system_prompt, user_prompt, route = build_writing_assist_prompt(
        chapter_num,
        mode,
        user_request=user_request,
        selected_text=selected_text,
        use_rag=use_rag,
    )
    router = llm or LLMRouter(project_dir=PROJECT_DIR)
    workflow = WRITING_ASSIST_MODES[mode]["workflow"]
    if route == "revise":
        result = router.revise_text(
            system_prompt,
            user_prompt,
            workflow=workflow,
            role="writing_assistant",
        )
    else:
        result = router.assist_text(
            system_prompt,
            user_prompt,
            workflow=workflow,
            role="writing_assistant",
        )
    ch = ch_str(chapter_num)
    safe_mode = re.sub(r"[^\w\u4e00-\u9fff]+", "_", mode).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return write_file(
        f"04_审核日志/第{ch}章_AI辅助_{safe_mode}_{timestamp}.md",
        result,
        preserve_existing=False,
    )

def build_hook_assist_request(report: dict | None = None) -> str:
    metrics = (report or {}).get("metrics", {})
    opening_score = int(metrics.get("opening_hook_score", 0) or 0)
    ending_score = int(metrics.get("ending_hook_score", 0) or 0)
    page_turner = int(metrics.get("page_turner_score", 0) or 0)
    reader_grip = int(metrics.get("reader_grip_score", 0) or 0)
    lines = [
        "## 首尾钩子增强指令",
        f"- 当前章首抓力：{opening_score}/100；章末余味：{ending_score}/100。",
        f"- 当前追读张力：{page_turner}/100；读者抓力：{reader_grip}/100。",
        "- 章首目标：前三百字内给出异常、压力或不可回避的问题，让主角必须做出动作或选择。",
        "- 章末目标：留下更具体的未解信息、反常细节、关系变化或情绪余波，让读者自然想翻下一章。",
        "- 中段目标：除必要衔接句外，尽量保留当前处理文本的事实、顺序和人物关系。",
    ]
    if opening_score >= 72:
        lines.append("- 章首已有基础抓力，重点做压缩和更锋利的第一处异常。")
    if ending_score >= 72:
        lines.append("- 章末已有基础余味，重点强化最后一段的落点，不要过度解释。")
    lines += [
        "",
        "## 输出格式",
        "- 先给出不超过三条改动说明。",
        "- 在“可直接采用文本”下输出完整章节修订稿：只替换章首和章末对应段落，中段必须保留当前处理文本原文。",
        "- 不新增硬设定，不提前揭露任务卡 forbidden，不改变本章核心事件。",
    ]
    return "\n".join(lines)

def run_hook_assist_package(
    chapter_num: int,
    mock: bool = False,
    llm=None,
    use_rag: bool = True,
) -> dict:
    ch = ch_str(chapter_num)
    source_rel, current_text = latest_chapter_text(ch)
    if not current_text.strip():
        raise FileNotFoundError(f"第{ch}章没有可增强正文")

    from quality_diagnostics import write_quality_diagnostics

    quality_md, quality_json, report = write_quality_diagnostics(PROJECT_DIR, chapter_num, current_text, source_rel)
    assist_path = run_writing_assist(
        chapter_num,
        "首尾钩子增强",
        user_request=build_hook_assist_request(report),
        selected_text=current_text,
        mock=mock,
        llm=llm,
        use_rag=use_rag,
    )
    candidate_path = save_writing_assist_candidate(chapter_num, assist_path)
    return {
        "source_rel": source_rel,
        "quality_md": quality_md,
        "quality_json": quality_json,
        "quality_report": report,
        "assist_path": assist_path,
        "candidate_path": candidate_path,
    }

def run_beautify_assist_package(
    chapter_num: int,
    mock: bool = False,
    llm=None,
    use_rag: bool = True,
) -> dict:
    ch = ch_str(chapter_num)
    source_rel, current_text = latest_chapter_text(ch)
    if not current_text.strip():
        raise FileNotFoundError(f"第{ch}章没有可精修正文")

    from quality_diagnostics import build_revision_checklist, merge_revision_requests, write_quality_diagnostics

    quality_md, quality_json, report = write_quality_diagnostics(PROJECT_DIR, chapter_num, current_text, source_rel)
    checklist = build_revision_checklist(report)
    assist_path = run_writing_assist(
        chapter_num,
        "好看度精修",
        user_request=merge_revision_requests(checklist, report.get("polish_targets", [])),
        selected_text=current_text,
        mock=mock,
        llm=llm,
        use_rag=use_rag,
    )
    candidate_path = save_writing_assist_candidate(chapter_num, assist_path)
    return {
        "source_rel": source_rel,
        "quality_md": quality_md,
        "quality_json": quality_json,
        "quality_report": report,
        "checklist": checklist,
        "polish_targets": report.get("polish_targets", []),
        "assist_path": assist_path,
        "candidate_path": candidate_path,
    }

def extract_adoptable_assist_text(content: str) -> str:
    text = _strip_outer_markdown_fence(content)
    lines = text.splitlines()
    captured: list[str] = []
    capture = False
    capture_level = 0

    for line in lines:
        heading = re.match(r"^(#{1,6})\s*(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip().strip(":：")
            if capture and level <= capture_level:
                break
            if any(marker in title for marker in ADOPTABLE_ASSIST_HEADINGS):
                capture = True
                capture_level = level
                captured = []
                continue
        if capture:
            captured.append(line)

    if captured:
        extracted = _strip_outer_markdown_fence("\n".join(captured)).strip()
        if extracted:
            return extracted
    return text.strip()

def save_writing_assist_candidate(chapter_num: int, assist_rel_path: str | Path) -> Path:
    source_path = _validate_writing_assist_log(chapter_num, assist_rel_path)
    extracted = extract_adoptable_assist_text(source_path.read_text(encoding="utf-8"))
    if not extracted.strip():
        raise ValueError("辅助稿中没有可提取的文本")
    ch = ch_str(chapter_num)
    return write_file(_unique_assist_candidate_rel(ch), extracted, preserve_existing=False)

def list_writing_assist_candidates(chapter_num: int) -> list[Path]:
    ch = ch_str(chapter_num)
    body_dir = PROJECT_DIR / "02_正文"
    if not body_dir.exists():
        return []
    candidates = [path for path in body_dir.glob(f"第{ch}章_AI辅助草案_*.md") if path.is_file()]
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)

def build_text_diff(
    old_text: str,
    new_text: str,
    from_label: str = "当前稿件",
    to_label: str = "辅助草案",
    context: int = 3,
) -> str:
    old_lines = (old_text or "").strip().splitlines()
    new_lines = (new_text or "").strip().splitlines()
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
            n=context,
        )
    )
    return "\n".join(diff_lines) if diff_lines else "两份文本一致。"

QUALITY_COMPARE_METRICS = [
    ("总分", "score", "分"),
    ("中文字数", "metrics.zh_chars", "字"),
    ("章首抓力", "metrics.opening_hook_score", "分"),
    ("章末余味", "metrics.ending_hook_score", "分"),
    ("追读张力", "metrics.page_turner_score", "分"),
    ("文气质地", "metrics.prose_texture_score", "分"),
    ("读者抓力", "metrics.reader_grip_score", "分"),
]

def _quality_report_value(report: dict, key: str) -> float:
    if key == "score":
        return float(report.get("score", 0) or 0)
    if key.startswith("metrics."):
        metric_key = key.split(".", 1)[1]
        return float(report.get("metrics", {}).get(metric_key, 0) or 0)
    return 0.0

def _format_quality_value(value: float, unit: str) -> str:
    if abs(value - round(value)) < 0.01:
        rendered = str(int(round(value)))
    else:
        rendered = f"{value:.1f}"
    return f"{rendered}{unit}" if unit else rendered

def _format_quality_delta(delta: float, unit: str) -> str:
    if abs(delta) < 0.01:
        return "持平"
    sign = "+" if delta > 0 else ""
    return f"{sign}{_format_quality_value(delta, unit)}"

def _candidate_quality_rows(source_report: dict, candidate_report: dict) -> list[dict[str, str]]:
    rows = []
    for label, key, unit in QUALITY_COMPARE_METRICS:
        before = _quality_report_value(source_report, key)
        after = _quality_report_value(candidate_report, key)
        rows.append(
            {
                "指标": label,
                "当前稿": _format_quality_value(before, unit),
                "辅助草案": _format_quality_value(after, unit),
                "变化": _format_quality_delta(after - before, unit),
            }
        )
    return rows

def compare_assist_candidate_quality(
    chapter_num: int,
    candidate_rel_path: str | Path,
    candidate_text: str | None = None,
) -> dict:
    candidate_path = _validate_writing_assist_candidate(chapter_num, candidate_rel_path)
    ch = ch_str(chapter_num)
    source_rel, source_text = latest_chapter_text(ch)
    if not source_text.strip():
        raise FileNotFoundError(f"第{ch}章没有可对比的当前稿")

    text = candidate_path.read_text(encoding="utf-8") if candidate_text is None else candidate_text.strip()
    if not text.strip():
        raise ValueError("辅助草案为空，无法生成质量对比")

    from quality_diagnostics import analyze_chapter_quality

    source_report = analyze_chapter_quality(PROJECT_DIR, chapter_num, source_text, source_rel)
    candidate_report = analyze_chapter_quality(PROJECT_DIR, chapter_num, text, _project_rel(candidate_path))
    warnings = []
    source_chars = int(source_report.get("metrics", {}).get("zh_chars", 0) or 0)
    candidate_chars = int(candidate_report.get("metrics", {}).get("zh_chars", 0) or 0)
    if source_chars and candidate_chars < source_chars * 0.7:
        warnings.append("辅助草案字数显著少于当前稿，采纳前请确认不是只生成了片段。")
    if float(candidate_report.get("score", 0) or 0) < float(source_report.get("score", 0) or 0):
        warnings.append("辅助草案总分低于当前稿，建议只摘取可用段落或继续精修。")
    forbidden_hits = candidate_report.get("task_card_alignment", {}).get("forbidden_hits", [])
    if forbidden_hits:
        warnings.append("辅助草案命中任务卡禁止事项：" + "、".join(forbidden_hits))

    return {
        "source_rel": source_rel,
        "candidate_rel": _project_rel(candidate_path),
        "source_report": source_report,
        "candidate_report": candidate_report,
        "rows": _candidate_quality_rows(source_report, candidate_report),
        "warnings": warnings,
    }

def promote_assist_candidate_to_revision(
    chapter_num: int,
    candidate_rel_path: str | Path,
    candidate_text: str | None = None,
) -> Path:
    candidate_path = _validate_writing_assist_candidate(chapter_num, candidate_rel_path)
    original = candidate_path.read_text(encoding="utf-8")
    text = original if candidate_text is None else candidate_text.strip()
    if not text.strip():
        raise ValueError("辅助草案为空，不能写入修订稿")
    if candidate_text is not None and text != original:
        write_file(_project_rel(candidate_path), text)
    ch = ch_str(chapter_num)
    return write_file(f"02_正文/第{ch}章_修订稿.md", text)

def _strip_outer_markdown_fence(text: str) -> str:
    stripped = (text or "").strip()
    match = re.match(r"^```[^\r\n]*\r?\n([\s\S]*?)\r?\n```$", stripped)
    return match.group(1).strip() if match else stripped

def _resolve_project_path(path_like: str | Path) -> Path:
    raw = Path(path_like)
    root = PROJECT_DIR.resolve()
    resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("路径必须位于当前书籍项目内") from exc
    return resolved

def _project_rel(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_DIR.resolve())).replace("\\", "/")

def _validate_writing_assist_log(chapter_num: int, path_like: str | Path) -> Path:
    path = _resolve_project_path(path_like)
    ch = ch_str(chapter_num)
    rel = _project_rel(path)
    if not rel.startswith("04_审核日志/") or not path.name.startswith(f"第{ch}章_AI辅助_") or path.suffix.lower() != ".md":
        raise ValueError("只能从本章 AI 辅助历史稿提取草案")
    if not path.exists():
        raise ValueError("AI 辅助历史稿不存在")
    return path

def _validate_writing_assist_candidate(chapter_num: int, path_like: str | Path) -> Path:
    path = _resolve_project_path(path_like)
    ch = ch_str(chapter_num)
    if path.parent.resolve() != (PROJECT_DIR / "02_正文").resolve():
        raise ValueError("只能采纳正文目录下的本章 AI 辅助草案")
    pattern = rf"^第{ch}章_AI辅助草案_\d{{8}}_\d{{6}}(?:_\d+)?\.md$"
    if not re.match(pattern, path.name):
        raise ValueError("只能采纳本章 AI 辅助草案")
    if not path.exists():
        raise ValueError("AI 辅助草案不存在")
    return path

def _unique_assist_candidate_rel(ch: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"02_正文/第{ch}章_AI辅助草案_{timestamp}.md"
    if not (PROJECT_DIR / base).exists():
        return base
    for idx in range(2, 100):
        rel = f"02_正文/第{ch}章_AI辅助草案_{timestamp}_{idx}.md"
        if not (PROJECT_DIR / rel).exists():
            return rel
    raise RuntimeError("无法生成唯一的 AI 辅助草案文件名")

def _writing_assist_text_window(current_text: str, selected_text: str, mode: str) -> str:
    chosen = selected_text.strip() or current_text.strip()
    if not chosen:
        return ""
    limit = 7000 if mode == "续写建议" else 10000
    if len(chosen) <= limit:
        return chosen
    return chosen[-limit:] if mode == "续写建议" else chosen[:limit]

def _writing_assist_context(outline: str, use_rag: bool = True) -> str:
    try:
        from prompt_assembly import build_chapter_context
        if use_rag:
            try:
                from rag_engine import NovelRAG

                return build_chapter_context(PROJECT_DIR, NovelRAG(str(PROJECT_DIR)), outline)
            except Exception:
                return build_chapter_context(PROJECT_DIR, None, outline)
        return build_chapter_context(PROJECT_DIR, None, outline)
    except Exception:
        parts = [
            read_file("05_项目管理/故事规格.md"),
            read_file("00_世界观/世界观.md"),
            read_file("00_世界观/文风档案.md"),
            read_file("01_大纲/总纲.md"),
            read_file("03_滚动记忆/最近摘要.md"),
        ]
        return "\n\n".join(part for part in parts if part.strip())

def _writing_assist_quality_context(chapter_num: int) -> str:
    ch = ch_str(chapter_num)
    json_text = read_file(f"04_审核日志/第{ch}章_质量诊断.json")
    if json_text.strip():
        try:
            from quality_diagnostics import render_revision_brief

            return render_revision_brief(json.loads(json_text))
        except Exception:
            return json_text[:5000]
    return read_file(f"04_审核日志/第{ch}章_质量诊断.md")[:5000]

# ─── 页面：书库 ─────────────────────────────────────────────────────────────

def activate_registered_book(book_id: str | None = None) -> dict:
    from book_manager import get_active_book, set_active_book

    active = set_active_book(APP_DIR, book_id) if book_id else get_active_book(APP_DIR)
    set_active_project(active["resolved_path"])
    return active


def _render_book_sidebar(active_book: dict) -> dict:
    from book_manager import create_book, list_books, set_active_book

    books = list_books(APP_DIR)
    id_to_book = {item["id"]: item for item in books}
    ids = list(id_to_book)
    active_id = active_book.get("id")
    index = ids.index(active_id) if active_id in ids else 0
    selected_id = st.selectbox(
        "当前书籍",
        ids,
        index=index,
        format_func=lambda item_id: id_to_book[item_id]["title"],
        key="book_selector",
    )
    if selected_id != active_id:
        active_book = set_active_book(APP_DIR, selected_id)
        set_active_project(active_book["resolved_path"])
        st.rerun()

    stats = active_book.get("stats", {})
    st.caption(
        f"章纲 {stats.get('chapter_outlines', 0)} ｜ "
        f"草稿 {stats.get('drafts', 0)} ｜ "
        f"定稿 {stats.get('finals', 0)}"
    )
    with st.expander("新建书籍", expanded=False):
        with st.form("quick_create_book"):
            title = st.text_input("书名", placeholder="例如：雨夜档案")
            brief = st.text_area("一句话灵感", height=80, placeholder="可留空，稍后在中台启动向导补。")
            submitted = st.form_submit_button("创建并切换", type="primary", use_container_width=True)
        if submitted:
            try:
                active_book = create_book(APP_DIR, title, brief=brief, activate=True)
                set_active_project(active_book["resolved_path"])
                st.success(f"已创建：{active_book['title']}")
                st.rerun()
            except Exception as exc:
                st.error(f"创建失败：{exc}")
    return active_book


def page_books():
    from book_manager import create_book, import_book, list_books, remove_book, rename_book, set_active_book

    st.markdown(
        """
        <div class="novel-hero">
          <h1>书库</h1>
          <p>管理多本小说项目，切换后全站读写都会进入对应书籍目录</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    books = list_books(APP_DIR)
    rows = []
    for item in books:
        stats = item.get("stats", {})
        rows.append({
            "当前": "是" if item.get("active") else "",
            "书名": item.get("title", ""),
            "ID": item.get("id", ""),
            "章纲": stats.get("chapter_outlines", 0),
            "草稿": stats.get("drafts", 0),
            "定稿": stats.get("finals", 0),
            "目录": item.get("resolved_path", ""),
            "状态": "可用" if item.get("exists") else "目录缺失",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    ids = [item["id"] for item in books]
    id_to_book = {item["id"]: item for item in books}
    active_id = next((item["id"] for item in books if item.get("active")), ids[0] if ids else "")
    selected_id = st.selectbox(
        "选择要管理的书籍",
        ids,
        index=ids.index(active_id) if active_id in ids else 0,
        format_func=lambda item_id: id_to_book[item_id]["title"],
        key="library_manage_book",
    )
    selected = id_to_book[selected_id]
    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("切换到此书", type="primary", use_container_width=True, disabled=selected.get("active")):
        active = set_active_book(APP_DIR, selected_id)
        set_active_project(active["resolved_path"])
        st.rerun()
    remove_confirm = c2.checkbox("确认移除", key=f"remove_book_confirm_{selected_id}", disabled=selected_id == "root")
    if c2.button("从书库移除", use_container_width=True, disabled=selected_id == "root" or not remove_confirm):
        try:
            remove_book(APP_DIR, selected_id)
            st.success("已从书库移除；文件仍保留在原目录。")
            st.rerun()
        except Exception as exc:
            st.error(f"移除失败：{exc}")
    c3.caption(f"当前目录：{selected.get('resolved_path', '')}")

    with st.form(f"rename_book_form_{selected_id}"):
        new_title = st.text_input("显示书名", value=selected.get("title", ""), key=f"rename_book_title_{selected_id}")
        submitted = st.form_submit_button("保存书名", use_container_width=True)
    if submitted:
        try:
            renamed = rename_book(APP_DIR, selected_id, new_title)
            if renamed["id"] == active_id:
                set_active_project(renamed["resolved_path"])
            st.success(f"已改名为：{renamed['title']}")
            st.rerun()
        except Exception as exc:
            st.error(f"改名失败：{exc}")

    tab_create, tab_import = st.tabs(["新建书籍", "导入已有目录"])
    with tab_create:
        with st.form("create_book_form"):
            title = st.text_input("书名", key="create_book_title")
            slug = st.text_input("目录名（可选）", key="create_book_slug", help="留空时自动由书名生成。")
            brief = st.text_area("一句话灵感 / 备注", key="create_book_brief", height=120)
            submitted = st.form_submit_button("创建书籍并切换", type="primary", use_container_width=True)
        if submitted:
            try:
                active = create_book(APP_DIR, title, brief=brief, slug=slug, activate=True)
                set_active_project(active["resolved_path"])
                st.success(f"已创建并切换到：{active['title']}")
                st.rerun()
            except Exception as exc:
                st.error(f"创建失败：{exc}")

    with tab_import:
        with st.form("import_book_form"):
            path_text = st.text_input("已有项目目录", placeholder=r"D:\novels\my_book")
            title = st.text_input("显示书名（可选）", key="import_book_title")
            submitted = st.form_submit_button("导入并切换", type="primary", use_container_width=True)
        if submitted:
            try:
                active = import_book(APP_DIR, path_text, title=title, activate=True)
                set_active_project(active["resolved_path"])
                st.success(f"已导入并切换到：{active['title']}")
                st.rerun()
            except Exception as exc:
                st.error(f"导入失败：{exc}")

# ─── 页面：仪表盘 ────────────────────────────────────────────────────────────

def page_dashboard():
    from workflow_advisor import workspace_dashboard

    dashboard = workspace_dashboard(PROJECT_DIR)
    outlines = list_md("01_大纲/章纲")
    totals = dashboard.get("totals", {})
    st.markdown(
        f"""
        <div class="novel-hero">
          <h1>智能写作工作台</h1>
          <p>{totals.get('chapters', 0)} 章规划 · {totals.get('active', 0)} 个可执行步骤 · {totals.get('blocked', 0)} 个阻断项</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    onboarding = dashboard.get("onboarding") or {}
    if onboarding.get("stage") and onboarding["stage"] != "writing":
        _render_onboarding_panel(onboarding, primary=not outlines)

    if outlines:
        chapter_options = [parse_chapter_num(name) for name in outlines if parse_chapter_num(name)]
        default_chapter = dashboard.get("active_chapter") or chapter_options[0]
        index = chapter_options.index(default_chapter) if default_chapter in chapter_options else 0
        binder, main_panel, inspector = st.columns([0.95, 2.15, 1.05])
        with binder:
            st.markdown('<div class="novel-card"><h3>章节 Binder</h3>', unsafe_allow_html=True)
            active_chapter = st.selectbox(
                "当前章节",
                chapter_options,
                index=index,
                format_func=lambda num: f"第{num:03d}章",
            )
            with st.container(height=420, border=False):
                for card in dashboard["chapters"]:
                    rec = card["recommendation"]
                    css = "active" if card["chapter_number"] == active_chapter else ""
                    badge_class = {"blocked": "bad", "action": "warn", "confirm": "warn", "done": "good"}.get(rec["severity"], "")
                    st.markdown(
                        f"""
                        <div class="novel-binder-item {css}">
                          <span>{html_escape(card['title'])}</span>
                          <span class="novel-chip {badge_class}">{html_escape(rec['label'])}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            st.caption(f"运行模式：{'Mock 离线' if st.session_state.get('_global_mock', False) else '真实调用'}")
            allow_blocked = st.checkbox("允许测试性执行阻断步骤", value=False, key="dashboard_allow_blocked")
            st.markdown("</div>", unsafe_allow_html=True)
        with main_panel:
            _render_smart_action_panel(active_chapter, mock=st.session_state.get("_global_mock", False), allow_blocked=allow_blocked, key_prefix="dashboard")
        with inspector:
            _render_project_inspector(dashboard)
    else:
        if onboarding.get("stage") == "writing":
            st.info("暂无章纲，请先到「大纲」页面创建第一章。")

    chars = [c for c in list_md("00_世界观/角色档案") if c != "角色模板.md"]
    finals = list((PROJECT_DIR / "02_正文").glob("*_定稿.md")) if (PROJECT_DIR / "02_正文").exists() else []
    drafts = list((PROJECT_DIR / "02_正文").glob("*_草稿.md")) if (PROJECT_DIR / "02_正文").exists() else []

    st.divider()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("角色", len(chars))
    c2.metric("章纲", len(outlines))
    c3.metric("草稿", len(drafts))
    c4.metric("定稿", len(finals))
    c5.metric("进度", f"{len(finals)}/{len(outlines)}" if outlines else "0/0")

    placeholder_count = len(scan_placeholders())
    if placeholder_count:
        st.warning(f"发现 {placeholder_count} 处待补占位符，正式生成前建议先处理。")

    st.divider()
    if dashboard["chapters"]:
        st.subheader("章节流程")
        rows = []
        for card in dashboard["chapters"]:
            rec = card["recommendation"]
            rows.append({
                "章节": f"第{card['chapter_number']:03d}章",
                "标题": card["title"],
                "下一步": rec["label"],
                "状态": rec["severity"],
                "场景": f"{card['scenes']['drafted']}/{card['scenes']['total']}",
                "草稿": "有" if card["artifacts"]["draft"] else "无",
                "定稿": "有" if card["artifacts"]["final"] else "无",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()

    # V3.1 跨章节戏剧趋势
    _render_drama_trends_section()

    # V4.0 Phase D 章节健康热力图
    _render_chapter_health_heatmap()

    st.divider()

    col_a, col_b = st.columns([1, 1])

    with col_a:
        st.subheader("伏笔状态")
        foreshadow = read_file("03_滚动记忆/伏笔追踪.md")
        rows = [l for l in foreshadow.split("\n") if l.startswith("|") and "---" not in l and "编号" not in l]
        pending = [r for r in rows if "待回收" in r]
        done = [r for r in rows if "已回收" in r]
        aborted = [r for r in rows if "作废" in r or "已作废" in r]
        fc1, fc2, fc3 = st.columns(3)
        fc1.metric("待回收", len(pending))
        fc2.metric("已回收", len(done))
        fc3.metric("作废", len(aborted))
        if pending:
            st.markdown("**待回收：**")
            for r in pending:
                parts = [p.strip() for p in r.split("|") if p.strip()]
                if len(parts) >= 3:
                    st.markdown(f"- `{parts[0]}` {parts[2]}")

    with col_b:
        st.subheader("章节进度")
        if outlines:
            for name in outlines:
                num = parse_chapter_num(name)
                status = chapter_status(num) if num else "待创作"
                st.text(f"{status} {name}")
        else:
            st.info("暂无章纲，请前往「大纲」页面创建")

    st.divider()
    st.subheader("最近章节摘要")
    recent = read_file("03_滚动记忆/最近摘要.md")
    if recent.strip() and "此处为空" not in recent and len(recent.strip()) > 30:
        st.markdown(recent)
    else:
        st.info("暂无摘要，完成第一章后自动更新")


def _render_smart_action_panel(chapter_num: int, mock: bool, allow_blocked: bool, key_prefix: str):
    from workflow_advisor import chapter_flow

    flow = chapter_flow(PROJECT_DIR, chapter_num)
    rec = flow["recommendation"]
    status_text = {
        "blocked": "需要先处理",
        "action": "可执行",
        "confirm": "需要确认",
        "done": "已完成",
    }.get(rec["severity"], rec["severity"])
    st.markdown(
        f"""
        <div class="novel-card">
          <h3>第{chapter_num:03d}章：{html_escape(flow['title'])}</h3>
          <div class="novel-muted">当前步骤 · {html_escape(rec['label'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_step_metrics(flow["steps"])

    if rec["severity"] == "blocked":
        st.warning(f"{status_text}：{rec['detail']}")
        if flow["placeholders"]:
            with st.expander("占位符位置", expanded=True):
                st.dataframe(flow["placeholders"], use_container_width=True, hide_index=True)
    elif rec["severity"] == "done":
        st.success(rec["detail"])
    elif rec["severity"] == "confirm":
        st.warning(rec["detail"])
    else:
        st.info(rec["detail"])

    c1, c2 = st.columns([1, 2])
    disabled = rec["severity"] in {"done"} or (rec["severity"] == "blocked" and not allow_blocked) or _is_llm_running()
    if c1.button(rec["label"], type="primary", use_container_width=True, disabled=disabled, key=f"{key_prefix}_smart_action_{chapter_num}_{rec['action']}"):
        _run_smart_action(chapter_num, rec, mock=mock)
    with c2:
        st.caption(_smart_action_hint(rec["action"]))


def _render_onboarding_panel(onboarding: dict, primary: bool):
    progress = onboarding.get("progress", 0)
    total = onboarding.get("total", 0)
    next_step = onboarding.get("next_step", "")
    stage = onboarding.get("stage", "spec")
    stage_label = {
        "spec": "故事规格",
        "world": "世界观",
        "outline": "总纲",
        "characters": "主角档案",
        "chapters": "第一章章纲",
        "writing": "正常写作",
    }.get(stage, stage)
    chips = "".join(
        f'<span class="novel-chip {"good" if step["done"] else "warn"}">'
        f'{"已完成 " if step["done"] else ""}{html_escape(step["name"])}</span>'
        for step in onboarding.get("steps", [])
    )
    headline = "启动向导" if primary else "启动向导（背景任务）"
    st.markdown(
        f"""
        <div class="novel-card">
          <h3>{headline} · {progress}/{total}</h3>
          <div class="novel-muted">当前阶段：{html_escape(stage_label)}</div>
          <div style="margin-top:8px;">{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if primary:
        st.info(next_step)
    else:
        st.caption(next_step)
    with st.expander("查看启动清单与跳转指引", expanded=primary):
        first_undone_shown = False
        for step in onboarding.get("steps", []):
            if step["done"]:
                st.markdown(f"已完成：~~{step['name']}~~")
            elif not first_undone_shown:
                st.markdown(f"**下一步：{step['name']}** — 前往：**{step['location']}**")
                first_undone_shown = True
            else:
                st.markdown(f"待处理：{step['name']} — {step['location']}")
        st.caption(
            "建议顺序：故事规格（今天）→ 世界观（笔记）→ 总纲（全书）→ 至少一位主角档案（笔记）→ 第一章章纲（全书）。"
            "完成后会自动进入章节流水线。"
        )
        st.caption(
            "提示：「今天 → 启动向导」可一键生成故事规格、世界观、总纲和角色草案；草案也可在对应页面原地查看和采纳。"
        )


def _render_project_inspector(dashboard: dict):
    project = dashboard.get("project") or {}
    blockers = project.get("blockers", [])
    warnings = project.get("warnings", [])
    next_actions = project.get("next_actions", [])
    status_label = "阻断" if blockers else ("风险" if warnings else "顺畅")
    status_class = "bad" if blockers else ("warn" if warnings else "good")
    st.markdown(
        f"""
        <div class="novel-card">
          <h3>Inspector</h3>
          <span class="novel-chip {status_class}">{status_label}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if blockers:
        st.error(blockers[0])
    elif warnings:
        st.warning(warnings[0])
    else:
        st.success("项目状态正常")

    # V5.0-rc1 三指标文学健康卡片
    try:
        from project_center import compute_project_health
        health = compute_project_health(PROJECT_DIR)
        if health.total_chapters_diagnosed > 0:
            st.markdown('<div class="novel-card"><h3>文学健康</h3>', unsafe_allow_html=True)
            trend_icon = {"improving": "↗", "declining": "↘", "stable": "→"}
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "工程稳健度",
                f"{health.engineering_sturdiness:.0f}",
                delta=trend_icon.get(health.engineering_trend, ""),
            )
            c2.metric(
                "文学密度",
                f"{health.literary_density:.0f}",
                delta=trend_icon.get(health.literary_trend, ""),
            )
            c3.metric(
                "风格一致度",
                f"{health.style_consistency:.0f}",
                delta=trend_icon.get(health.style_trend, ""),
            )
            # 弱章提示
            hints = []
            if health.weakest_chapter_engineering:
                hints.append(f"第{health.weakest_chapter_engineering:03d}章工程最弱")
            if health.weakest_chapter_literary:
                hints.append(f"第{health.weakest_chapter_literary:03d}章文学密度最低")
            if health.most_style_drifted_chapter:
                hints.append(f"第{health.most_style_drifted_chapter:03d}章风格漂移最大")
            if hints:
                st.caption(" · ".join(hints))
            st.markdown("</div>", unsafe_allow_html=True)
    except Exception:
        pass

    if next_actions:
        st.markdown('<div class="novel-card"><h3>下一步</h3>', unsafe_allow_html=True)
        for item in next_actions[:3]:
            st.markdown(f"- {item}")
        st.markdown("</div>", unsafe_allow_html=True)
    metrics = project.get("metrics", {})
    if metrics:
        st.markdown('<div class="novel-card"><h3>项目指标</h3>', unsafe_allow_html=True)
        st.caption(
            f"任务卡 {metrics.get('confirmed_task_cards', 0)}/{metrics.get('task_cards', 0)} ｜ "
            f"伏笔待回收 {metrics.get('pending_foreshadows', 0)} ｜ "
            f"占位符 {metrics.get('placeholders', 0)}"
        )
        st.markdown("</div>", unsafe_allow_html=True)


def _render_drama_trends_section():
    """V3.1 仪表板跨章节戏剧趋势区块。"""
    trends = compute_drama_trends(PROJECT_DIR)
    chapters = [s for s in trends.chapters if not s.is_mock]
    mock_chapters = [s for s in trends.chapters if s.is_mock]

    st.subheader("戏剧趋势")

    if not chapters and not mock_chapters:
        st.caption("暂无诊断数据，完成章节审核后出现。")
        return

    direction_emoji = {
        "improving": "↗",
        "declining": "↘",
        "stable": "→",
        "insufficient_data": "…",
    }.get(trends.trend_direction, "…")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("趋势", direction_emoji)
    c2.metric("压力均值", f"{trends.avg_pressure:.0f}")
    c3.metric("弧光均值", f"{trends.avg_arc:.0f}")
    c4.metric("画面均值", f"{trends.avg_cinematic:.0f}")
    with c5:
        if chapters:
            latest = chapters[-1]
            avg = round(sum(s.overall_drama_score for s in chapters) / len(chapters))
            delta = latest.overall_drama_score - avg if len(chapters) > 1 else 0
            st.metric("综合 (最新章)", f"{latest.overall_drama_score}", delta=f"{'+' if delta > 0 else ''}{delta}")
        else:
            st.metric("综合 (最新章)", "—")

    if chapters:
        with st.expander("章节分数明细", expanded=False):
            rows = []
            for s in trends.chapters:
                rows.append({
                    "章节": f"第{s.chapter_number:03d}章",
                    "压力": s.pressure_curve_score,
                    "弧光": s.character_arc_score,
                    "画面": s.cinematic_score,
                    "综合": s.overall_drama_score,
                    "数据源": "Mock" if s.is_mock else "LLM",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

    if trends.rolling_avg_overall:
        st.caption(f"3 章滚动均值: {', '.join(f'{v:.0f}' for v in trends.rolling_avg_overall)}")
    if mock_chapters:
        st.caption(f"含 {len(mock_chapters)} 个 mock 诊断章 (mock 数据不参与均值与趋势计算)")


def _render_chapter_health_heatmap() -> None:
    """V5.0-beta1: 卷轴式全书健康图。"""
    st.divider()
    st.subheader("全书健康卷轴")
    render_scroll_health(PROJECT_DIR)


def _chapter_outline_template(chapter_num: int) -> str:
    """Return a usable chapter-outline template after the test 第001章 is removed."""
    chapter_dir = PROJECT_DIR / "01_大纲" / "章纲"
    for path in sorted(chapter_dir.glob("第*章.md")):
        text = path.read_text(encoding="utf-8")
        if text.strip():
            return text
    ch = f"{chapter_num:03d}"
    return (
        f"# 第{ch}章\n\n"
        "## 本章定位\n"
        "- 章节模式：plot\n"
        "- 节奏：normal\n"
        "- 结尾方式：hook\n\n"
        "## 核心事件\n"
        "- \n\n"
        "## 人物推进\n"
        "- \n\n"
        "## 伏笔与限制\n"
        "- 埋下：\n"
        "- 回收：\n"
        "- 禁止：\n\n"
        "## 章末画面\n"
        "- \n"
    )


def _render_step_metrics(steps: list[dict], max_cols: int = 5):
    if not steps:
        return
    for start in range(0, len(steps), max_cols):
        row = steps[start:start + max_cols]
        cols = st.columns(len(row))
        for col, step in zip(cols, row):
            col.metric(step["name"], "完成" if step["done"] else "待办")


def _smart_action_hint(action: str) -> str:
    hints = {
        "edit_outline": "会打开章纲编辑区；正式生成前建议消除所有占位符。",
        "generate_task_card": "会从章纲生成结构化 JSON，不覆盖章纲原文。",
        "confirm_task_card": "会把任务卡标记为 confirmed，表示章节目标已人工确认。",
        "plan_scenes": "会优先用 LLM 把任务卡拆成 2-6 个场景，异常时降级为保守模板。",
        "draft_scene": "会为第一个缺失场景生成一个新候选稿版本。",
        "assemble_scenes": "会把各场景已选或最新候选稿合并成章节草稿。",
        "full_pipeline": "会生成草稿，依次运行审计、读者镜像、质量诊断、文学批评、风格法庭、声音诊断、编辑备忘录；氛围/留白章节自动跳过戏剧诊断。",
        "audit": "只对当前稿运行逻辑审计。",
        "reader_mirror": "从目标读者视角审视本章，不纠语言细节（参考层，不进 P0 必改）。",
        "quality_diag": "本地生成章节质量诊断（节奏/对白/套话/任务卡对齐），不额外消耗模型 token。",
        "drama_diag": "戏剧结构诊断（压力曲线/弧光/画面）；interior / atmosphere / bridge 模式章节自动跳过。",
        "literary_critic": "文学批评：观察可被记住的瞬间、未说之语、自我欺骗——人味的核心保护层。",
        "style_court": "风格法庭：把工程诊断和文学批评的冲突分流为必改 vs 可争议。",
        "voice_diag": "角色声音诊断：本地分析对白指纹是否区分得开。",
        "editor_memo": "综合所有诊断生成编辑备忘录（P0/P1/P2 必改项 + 改稿约束）。",
        "feedback_revise": "按编辑备忘录调用改稿模型生成修订稿并复查（仅在硬伤触发）。",
        "save_final": "会把修订稿或草稿复制成定稿草案，仍需人工精修。",
        "finalize_memory": "会更新长期记忆和 RAG，建议确认定稿文本后执行。",
        "complete": "本章已闭环。",
    }
    return hints.get(action, "")


def _run_smart_action(chapter_num: int, recommendation: dict, mock: bool):
    action = recommendation["action"]
    label = recommendation["label"]

    def work(cancel_event):
        messages: list[str] = []
        apply_runtime_mode(mock)
        ch = ch_str(chapter_num)
        if action == "generate_task_card":
            from llm_router import LLMRouter
            from prompt_assembly import build_axis_context
            from structured_store import sync_task_card_from_outline
            llm = LLMRouter(project_dir=PROJECT_DIR)
            card = sync_task_card_from_outline(
                PROJECT_DIR,
                chapter_num,
                read_file(f"01_大纲/章纲/第{ch}章.md"),
                preserve_confirmation=False,
                llm=llm,
                context=build_axis_context(PROJECT_DIR),
            )
            messages.append(f"任务卡已生成：{card.title}")
        elif action == "confirm_task_card":
            from structured_store import confirm_task_card
            card = confirm_task_card(PROJECT_DIR, chapter_num)
            messages.append(f"任务卡已确认：{card.title}")
        elif action == "plan_scenes":
            from llm_router import LLMRouter
            from prompt_assembly import build_axis_context
            from structured_store import sync_scene_plan_from_task_card
            llm = LLMRouter(project_dir=PROJECT_DIR)
            scenes = sync_scene_plan_from_task_card(PROJECT_DIR, chapter_num, llm=llm, context=build_axis_context(PROJECT_DIR))
            messages.append(f"场景计划已生成：{len(scenes)} 个场景")
        elif action == "draft_scene":
            from novel_pipeline import run_scene_draft
            scene_number = int(recommendation.get("scene_number", 1))
            run_scene_draft(chapter_num, scene_number, mock=mock)
            messages.append(f"场景 {scene_number:03d} 候选稿已生成")
        elif action == "assemble_scenes":
            from novel_pipeline import run_assemble_scenes
            run_assemble_scenes(chapter_num)
            messages.append("场景已合并为章节草稿")
        elif action == "full_pipeline":
            from novel_pipeline import run_full
            run_full(chapter_num, mock=mock)
            messages.append("完整流水线已完成")
        elif action == "audit":
            from novel_pipeline import run_audit_only
            run_audit_only(chapter_num, mock=mock)
            messages.append("审计已完成")
        elif action == "reader_mirror":
            source, text = latest_chapter_text(ch)
            if not text:
                raise RuntimeError("找不到可检查稿件")
            from llm_router import LLMRouter
            recent = read_file("03_滚动记忆/最近摘要.md")
            result = LLMRouter(project_dir=PROJECT_DIR).reader_mirror(text, recent or "")
            write_file(f"04_审核日志/第{ch}章_读者镜像.md", result)
            messages.append(f"读者镜像已保存，来源：{source}")
        elif action == "quality_diag":
            source, text = latest_chapter_text(ch)
            if not text:
                raise RuntimeError("找不到可诊断稿件")
            from quality_diagnostics import write_quality_diagnostics
            _, _, report = write_quality_diagnostics(PROJECT_DIR, chapter_num, text, source)
            messages.append(f"质量诊断已保存：{report['score']}分，{report['grade']}")
        elif action == "drama_diag":
            source, text = latest_chapter_text(ch)
            if not text:
                raise RuntimeError("找不到可诊断稿件")
            from dramatic_arc_diagnostics import (
                build_character_briefs,
                diagnose_chapter_drama,
                write_diagnostics,
            )
            from llm_router import LLMRouter
            from structured_store import read_task_card
            card = read_task_card(PROJECT_DIR, chapter_num)
            diag = diagnose_chapter_drama(
                PROJECT_DIR,
                chapter_num,
                text,
                task_card_json=card.model_dump_json(indent=2) if card else "",
                character_briefs=build_character_briefs(PROJECT_DIR, text),
                llm=LLMRouter(project_dir=PROJECT_DIR),
            )
            write_diagnostics(PROJECT_DIR, diag)
            messages.append(f"戏剧诊断已保存（总分 {diag.overall_drama_score}）")
        elif action == "literary_critic":
            source, text = latest_chapter_text(ch)
            if not text:
                raise RuntimeError("找不到可批评稿件")
            from literary_critic import analyze_literary_view, write_literary_view
            from llm_router import LLMRouter
            from structured_store import read_task_card
            card = read_task_card(PROJECT_DIR, chapter_num)
            view = analyze_literary_view(
                PROJECT_DIR,
                chapter_num,
                text,
                task_card_json=card.model_dump_json(indent=2) if card else "",
                llm=LLMRouter(project_dir=PROJECT_DIR),
            )
            write_literary_view(PROJECT_DIR, view)
            messages.append("文学批评已保存（不打分，不制造必改项）")
        elif action == "style_court":
            from style_court import adjudicate, write_style_court
            from literary_critic import read_literary_view
            from structured_store import read_task_card
            quality_report = json.loads(
                read_file(f"04_审核日志/第{ch}章_质量诊断.json") or "{}"
            )
            literary = read_literary_view(PROJECT_DIR, chapter_num)
            if literary is None:
                raise RuntimeError("先生成文学批评再运行风格法庭。")
            decision = adjudicate(
                PROJECT_DIR,
                chapter_num,
                quality_report=quality_report,
                literary_view=literary,
                task_card=read_task_card(PROJECT_DIR, chapter_num),
            )
            write_style_court(PROJECT_DIR, decision)
            messages.append(
                f"风格法庭已裁决：confirmed={len(decision.confirmed_issues)} / contested={len(decision.contested_issues)}"
            )
        elif action == "voice_diag":
            from voice_diagnostics import (
                analyze_character_voices,
                write_voice_diagnostics,
            )
            fp = analyze_character_voices(PROJECT_DIR, chapter_num)
            write_voice_diagnostics(PROJECT_DIR, fp)
            messages.append("角色声音诊断已保存")
        elif action == "editor_memo":
            source, text = latest_chapter_text(ch)
            if not text:
                raise RuntimeError("找不到可备忘的稿件")
            from editor_memo import synthesize_memo, write_memo
            from literary_critic import read_literary_view
            from style_court import read_style_court
            from dramatic_arc_diagnostics import read_diagnostics as _read_drama
            quality_report = json.loads(
                read_file(f"04_审核日志/第{ch}章_质量诊断.json") or "{}"
            )
            memo = synthesize_memo(
                PROJECT_DIR,
                chapter_num,
                text,
                audit_text=read_file(f"04_审核日志/第{ch}章_审计.md"),
                reader_mirror_text=read_file(f"04_审核日志/第{ch}章_读者镜像.md"),
                quality_report=quality_report or None,
                drama_diag=_read_drama(PROJECT_DIR, chapter_num),
                literary_view=read_literary_view(PROJECT_DIR, chapter_num),
                style_court_decision=read_style_court(PROJECT_DIR, chapter_num),
            )
            write_memo(PROJECT_DIR, memo)
            messages.append(f"编辑备忘录已保存（必改项 {len(memo.top_3_must_fix)} 条）")
        elif action == "feedback_revise":
            from novel_pipeline import run_revise_from_feedback
            run_revise_from_feedback(chapter_num, mock=mock)
            messages.append("诊断驱动修订稿已生成，并已完成复审与质量诊断")
        elif action == "save_final":
            src = f"02_正文/第{ch}章_修订稿.md" if read_file(f"02_正文/第{ch}章_修订稿.md") else f"02_正文/第{ch}章_草稿.md"
            write_file(f"02_正文/第{ch}章_定稿.md", read_file(src))
            messages.append("已保存为定稿草案")
        elif action == "finalize_memory":
            from novel_pipeline import run_finalize
            run_finalize(chapter_num, yes=True, mock=mock)
            messages.append("长期记忆已更新")
        elif action == "edit_outline":
            messages.append("请在写作页或大纲页补全章纲占位符。")
        return messages

    def done(messages):
        for message in messages or []:
            st.success(message)

    def failed(error: str):
        st.error(f"执行失败：{error.splitlines()[-1] if error else '未知错误'}")

    _start_llm_background_job(
        f"执行：{label}",
        work,
        eta_seconds=120 if action in {"full_pipeline", "feedback_revise", "finalize_memory"} else 75,
        on_success=done,
        on_error=failed,
    )

def render_chapter_status_card(chapter_num: int) -> dict:
    state = chapter_state(chapter_num)
    flow_steps = state.get("flow_steps") or []
    _render_step_metrics(flow_steps)

    action = next_action_for_state(state)
    severity = state.get("recommendation", {}).get("severity", "")
    if severity == "done":
        st.success(f"下一步：{action}")
    elif severity == "blocked" or state["placeholders"]:
        st.warning(f"下一步：{action}")
        with st.expander("本章占位符"):
            st.dataframe(state["placeholders"], use_container_width=True, hide_index=True)
    else:
        st.info(f"下一步：{action}")
    return state

# ─── 页面：世界观 ────────────────────────────────────────────────────────────

def page_worldbuilding():
    st.title("世界观")
    tab_world, tab_chars, tab_assist = st.tabs(["世界设定", "角色档案", "AI辅助"])

    with tab_world:
        _md_editor("00_世界观/世界观.md", key="world")

    with tab_chars:
        chars = [c for c in list_md("00_世界观/角色档案") if c != "角色模板.md"]
        # 检测同名重复档案（相同 stem 的多个文件）
        from collections import Counter
        stems = Counter(Path(c).stem.rstrip("0123456789_").rstrip("_") for c in chars)
        dupes = [name for name, cnt in stems.items() if cnt > 1]
        if dupes:
            st.warning(f"检测到可能重复的角色档案（{', '.join(dupes)}），建议合并或删除多余文件，避免正文生成时产生冲突。")
        left, right = st.columns([1, 2])

        with left:
            st.subheader("角色列表")
            new_name = st.text_input("新角色名", placeholder="输入后点创建")
            if st.button("＋ 创建角色", use_container_width=True) and new_name.strip():
                try:
                    filename = safe_character_filename(new_name)
                    template = read_file("00_世界观/角色档案/角色模板.md")
                    write_file(f"00_世界观/角色档案/{filename}",
                               template.replace("【角色名】", Path(filename).stem))
                    st.success(f"已创建 {filename}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"创建失败：{exc}")
            st.divider()
            selected = st.radio("选择角色", chars if chars else ["（暂无角色）"],
                                label_visibility="collapsed")

        with right:
            if chars and selected in chars:
                st.subheader(selected.replace(".md", ""))
                with st.expander("修改名称", expanded=False):
                    with st.form(f"rename_character_{selected}"):
                        renamed_to = st.text_input("角色名", value=Path(selected).stem, key=f"rename_character_name_{selected}")
                        overwrite = st.checkbox(
                            "若同名档案已存在，确认覆盖",
                            value=False,
                            key=f"rename_character_overwrite_{selected}",
                            help="覆盖前会备份被覆盖的同名档案，也会备份当前角色档案。",
                        )
                        submitted = st.form_submit_button("保存名称", use_container_width=True)
                    if submitted:
                        try:
                            path = rename_character_profile(selected, renamed_to, overwrite=overwrite)
                            st.success(f"已改名为：{path.name}")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"改名失败：{exc}")
                with st.expander("删除角色档案", expanded=False):
                    st.caption("会移动到 `99_回收站/角色档案/`，不会直接粉碎文件。")
                    delete_reason = st.text_input("删除原因", key=f"delete_character_reason_{selected}")
                    if st.button(
                        "删除到回收站",
                        use_container_width=True,
                        key=f"delete_character_button_{selected}",
                    ):
                        try:
                            recycled = delete_character_profile(selected, reason=delete_reason)
                            st.success(f"已移入回收站：{recycled.relative_to(PROJECT_DIR)}")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"删除失败：{exc}")
                _md_editor(f"00_世界观/角色档案/{selected}", key=f"char_{selected}")

    with tab_assist:
        st.subheader("世界观辅助生成")
        world_brief = st.text_area("补充灵感", height=120, key="assist_world_brief")
        mock = st.session_state.get("_global_mock", False)
        st.caption(f"运行模式：{'Mock 离线' if mock else prose_model_label(mock)}")
        if st.button("生成世界观草案", type="primary", use_container_width=True, disabled=_is_llm_running()):
            def work(cancel_event):
                from planning_assist import generate_worldbuilding_draft
                apply_runtime_mode(mock)
                return str(generate_worldbuilding_draft(PROJECT_DIR, world_brief, mock=mock).relative_to(PROJECT_DIR))

            _start_llm_background_job(
                "生成世界观草案",
                work,
                eta_seconds=90,
                on_success=lambda rel: st.success(f"已生成：{rel}"),
            )

        st.divider()
        st.subheader("角色档案辅助生成")
        char_name = st.text_input("角色名", key="assist_char_name")
        char_brief = st.text_area("角色灵感", height=120, key="assist_char_brief")
        if st.button("生成角色档案草案", use_container_width=True, disabled=_is_llm_running()):
            def work(cancel_event):
                from planning_assist import generate_character_draft
                apply_runtime_mode(mock)
                return str(generate_character_draft(PROJECT_DIR, char_name, char_brief, mock=mock).relative_to(PROJECT_DIR))

            _start_llm_background_job(
                "生成角色档案草案",
                work,
                eta_seconds=90,
                on_success=lambda rel: st.success(f"已生成：{rel}"),
            )

        st.divider()
        st.subheader("批量角色档案生成")
        batch_count = st.number_input("生成数量", min_value=2, max_value=20, value=6, step=1, key="assist_char_batch_count")
        batch_brief = st.text_area(
            "批量要求",
            height=120,
            key="assist_char_batch_brief",
            placeholder="例如：围绕雨夜旧城旧案，生成主角、阻碍者、档案管理员、情感牵引者和灰度盟友。",
        )
        if st.button("根据世界设定批量生成角色档案", use_container_width=True, disabled=_is_llm_running()):
            def work(cancel_event):
                from planning_assist import generate_character_batch_drafts
                apply_runtime_mode(mock)
                paths = generate_character_batch_drafts(PROJECT_DIR, int(batch_count), batch_brief, mock=mock)
                return [str(path.relative_to(PROJECT_DIR)) for path in paths]

            def done(paths):
                st.success(f"已生成 {len(paths or [])} 份角色草案，可在本页下方查看和采纳。")

            _start_llm_background_job("批量角色档案生成", work, eta_seconds=150, on_success=done)

        st.divider()
        st.subheader("AI 审查 / 改稿")
        review_target = st.radio(
            "审查对象",
            ["世界观设定", "角色档案"],
            horizontal=True,
            key="world_review_target",
        )
        if review_target == "角色档案":
            char_files = [f for f in list_md("00_世界观/角色档案") if f != "角色模板.md"]
            if char_files:
                review_char = st.selectbox("选择角色", char_files, key="world_review_char")
            else:
                st.info("暂无角色档案。")
                review_char = None
        else:
            review_char = None

        col_rv, col_im = st.columns(2)
        review_key = f"review_result_world_{review_target}_{review_char}"
        _world_review_cache_key = f"world_{review_target}_{review_char or '世界观'}"
        review_subject_label = f"角色档案《{Path(review_char).stem}》" if review_target == "角色档案" and review_char else "世界观设定"
        review_job_name = f"{review_subject_label} AI 审查"
        improve_job_name = f"{review_subject_label} AI 改稿"
        review_result = st.session_state.get(review_key, "") or _load_review("world", _world_review_cache_key)
        if review_result and not st.session_state.get(review_key):
            st.session_state[review_key] = review_result

        world_review_widget_prefix = f"world_ai_{review_target}_{review_char or 'world'}"
        cached_review = _render_review_reload_controls(
            "world",
            _world_review_cache_key,
            review_key,
            f"{review_subject_label}审查",
            key_prefix=world_review_widget_prefix,
        )
        if not review_result and cached_review:
            review_result = cached_review

        if col_rv.button(
            "AI 审查",
            type="primary",
            use_container_width=True,
            disabled=_is_llm_running(),
            key=f"world_ai_review_{review_target}_{review_char or 'world'}",
        ):
            def work(cancel_event):
                from planning_assist import review_worldbuilding, review_character
                apply_runtime_mode(mock)
                if review_target == "角色档案" and review_char:
                    result = review_character(PROJECT_DIR, f"00_世界观/角色档案/{review_char}", mock=mock)
                else:
                    result = review_worldbuilding(PROJECT_DIR, mock=mock)
                _save_review("world", _world_review_cache_key, result)
                return result

            def done(result):
                st.session_state[review_key] = result
                st.success(f"{review_subject_label}审查完成")

            _start_llm_background_job(review_job_name, work, eta_seconds=90, on_success=done)

        edited_review_result = _render_editable_review_text(
            "world",
            _world_review_cache_key,
            review_key,
            review_result,
            "审查报告",
            key_prefix=world_review_widget_prefix,
        )

        improve_running = _is_llm_running()
        if col_im.button(
            "根据审查生成改稿",
            use_container_width=True,
            disabled=improve_running,
            key=f"world_ai_improve_{review_target}_{review_char or 'world'}",
        ):
            if not review_result:
                latest = _load_review("world", _world_review_cache_key)
                if latest:
                    review_result = latest
                    st.session_state[review_key] = latest
                    edited_review_result = latest
                else:
                    st.warning("还没有可用的审查报告。请先运行 AI 审查，完成后点「重新读取审查结果」。")
                    st.stop()
            review_for_improve = (edited_review_result or review_result or "").strip()
            if not review_for_improve:
                st.warning("审查意见为空，无法生成改稿。")
                st.stop()

            def work(cancel_event):
                from planning_assist import improve_worldbuilding, improve_character
                apply_runtime_mode(mock)
                if review_target == "角色档案" and review_char:
                    path = improve_character(PROJECT_DIR, f"00_世界观/角色档案/{review_char}", review_for_improve, mock=mock)
                else:
                    path = improve_worldbuilding(PROJECT_DIR, review_for_improve, mock=mock)
                return str(path.relative_to(PROJECT_DIR))

            _start_llm_background_job(
                improve_job_name,
                work,
                eta_seconds=90,
                on_success=lambda rel: st.success(f"改稿已保存到 AI 草案：{rel}"),
            )

        if not review_result:
            col_im.caption("先运行「AI 审查」再生成改稿")

        st.divider()
        _render_ai_draft_adoption(
            title="世界观 / 角色 AI 草案查看 / 采纳",
            source_prefixes=("00_世界观/",),
            empty_hint="暂无世界观或角色 AI 草案。可先在本页生成世界观、角色草案，或运行 AI 审查后生成改稿。",
        )

# ─── 页面：大纲 ─────────────────────────────────────────────────────────────

def page_outline():
    st.title("大纲")
    tab_total, tab_volumes, tab_chapters, tab_task_cards, tab_assist = st.tabs(["总纲", "卷/幕", "章纲", "任务卡", "AI辅助"])

    with tab_total:
        _md_editor("01_大纲/总纲.md", key="zonggang")

    with tab_volumes:
        from long_structure import ensure_default_volumes, list_volume_plans

        left, right = st.columns([1, 2])
        with left:
            st.subheader("卷/幕列表")
            count = st.number_input("初始化卷数", min_value=1, max_value=12, value=3, step=1)
            if st.button("初始化卷纲模板", type="primary", use_container_width=True):
                paths = ensure_default_volumes(PROJECT_DIR, int(count))
                st.success(f"已就绪 {len(paths)} 份卷纲")
                st.rerun()
            plans = list_volume_plans(PROJECT_DIR)
            if plans:
                for plan in plans:
                    chapter_range = ""
                    if plan.chapter_start is not None and plan.chapter_end is not None:
                        chapter_range = f"｜第{plan.chapter_start:03d}-{plan.chapter_end:03d}章"
                    st.caption(f"{plan.title}{chapter_range}")
            else:
                st.info("暂无卷纲。可先初始化模板。")
        with right:
            plans = list_volume_plans(PROJECT_DIR)
            if plans:
                selected_volume = st.selectbox("编辑卷纲", [p.path.name for p in plans], key="volume_plan_select")
                _md_editor(f"01_大纲/卷纲/{selected_volume}", key=f"volume_{selected_volume}", height=620)
            else:
                st.info("卷纲会作为长篇结构层进入项目轴、正文上下文和 RAG。")

    with tab_chapters:
        outlines = list_md("01_大纲/章纲")
        left, right = st.columns([1, 2])

        with left:
            st.subheader("章节列表")
            next_num = (parse_chapter_num(outlines[-1]) + 1) if outlines else 1
            new_num = st.number_input("新建第N章", min_value=1, value=next_num, step=1)
            if st.button("＋ 新建章纲", use_container_width=True):
                fname = f"第{new_num:03d}章.md"
                template = _chapter_outline_template(new_num)
                write_file(f"01_大纲/章纲/{fname}", template)
                st.success(f"已创建 {fname}")
                st.rerun()
            st.divider()
            for name in outlines:
                num = parse_chapter_num(name)
                st.text(f"{chapter_status(num) if num else '待创作'} {name}")
            st.divider()
            selected_outline = st.selectbox("编辑章纲", outlines if outlines else ["（暂无章纲）"])
            if selected_outline and selected_outline != "（暂无章纲）":
                outline_num = parse_chapter_num(selected_outline)
                if outline_num:
                    with st.expander("删除章节"):
                        _render_delete_chapter_controls(outline_num, key_prefix="outline")

        with right:
            if outlines and selected_outline and selected_outline != "（暂无章纲）":
                _md_editor(f"01_大纲/章纲/{selected_outline}", key=f"outline_{selected_outline}")

    with tab_task_cards:
        outlines = list_md("01_大纲/章纲")
        if not outlines:
            st.info("暂无章纲，先创建章纲。")
        else:
            selected_task_outline = st.selectbox("选择章节", outlines, key="task_card_chapter")
            task_num = parse_chapter_num(selected_task_outline)
            if not task_num:
                st.warning("无法识别章节号")
            else:
                ch = ch_str(task_num)
                outline_text = read_file(f"01_大纲/章纲/第{ch}章.md")
                info = task_card_info(task_num)
                c1, c2, c3 = st.columns(3)
                c1.metric("任务卡", "已生成" if info["exists"] else "未生成")
                c2.metric("状态", info["status"])
                c3.metric("确认", "已确认" if info["confirmed"] else "待确认")

                task_path = f"01_大纲/章纲/第{ch}章_task_card.json"
                if info["exists"]:
                    _render_task_card_v5_controls(task_path, ch)

                st.divider()
                if (PROJECT_DIR / task_path).exists():
                    _json_file_editor(task_path, key=f"task_card_json_{ch}", height=460)
                else:
                    st.info("任务卡尚未生成。")

    with tab_assist:
        st.subheader("总纲辅助生成")
        outline_brief = st.text_area("总纲灵感", height=120, key="assist_outline_brief")
        mock = st.session_state.get("_global_mock", False)
        st.caption(f"运行模式：{'Mock 离线' if mock else prose_model_label(mock)}")
        if st.button("生成总纲草案", type="primary", use_container_width=True, disabled=_is_llm_running()):
            def work(cancel_event):
                from planning_assist import generate_outline_draft
                apply_runtime_mode(mock)
                return str(generate_outline_draft(PROJECT_DIR, outline_brief, mock=mock).relative_to(PROJECT_DIR))

            _start_llm_background_job(
                "生成总纲草案",
                work,
                eta_seconds=90,
                on_success=lambda rel: st.success(f"已生成：{rel}"),
            )

        # "卷纲辅助生成" and "章纲辅助生成" removed to simplify the UI and fix the NameError.

        st.divider()
        st.subheader("AI 审查 / 改稿")
        outline_review_target = st.radio(
            "审查对象",
            ["总纲", "卷纲", "章纲"],
            horizontal=True,
            key="outline_review_target",
        )
        if outline_review_target == "卷纲":
            volume_review_files = list_md("01_大纲/卷纲")
            if volume_review_files:
                review_volume_name = st.selectbox("选择卷纲", volume_review_files, key="outline_review_volume")
            else:
                st.info("暂无卷纲。")
                review_volume_name = None
            review_ch_num = None
        elif outline_review_target == "章纲":
            outlines_list = list_md("01_大纲/章纲")
            if outlines_list:
                review_ch_name = st.selectbox("选择章节", outlines_list, key="outline_review_ch")
                review_ch_num = parse_chapter_num(review_ch_name) or 1
            else:
                st.info("暂无章纲。")
                review_ch_num = None
            review_volume_name = None
        else:
            review_ch_num = None
            review_volume_name = None

        outline_subject = Path(review_volume_name).stem if outline_review_target == "卷纲" and review_volume_name else (f"第{review_ch_num:03d}章" if outline_review_target == "章纲" and review_ch_num else "总纲")
        outline_review_key = f"review_result_outline_{outline_review_target}_{review_ch_num or review_volume_name or '总纲'}"
        _outline_cache_key = f"outline_{outline_review_target}_{review_ch_num or review_volume_name or '总纲'}"
        outline_review_result = st.session_state.get(outline_review_key, "") or _load_review("outline", _outline_cache_key)
        if outline_review_result and not st.session_state.get(outline_review_key):
            st.session_state[outline_review_key] = outline_review_result

        outline_review_widget_prefix = f"outline_ai_{outline_review_target}_{review_ch_num or review_volume_name or 'total'}"
        cached_outline_review = _render_review_reload_controls(
            "outline",
            _outline_cache_key,
            outline_review_key,
            f"{outline_subject}审查",
            key_prefix=outline_review_widget_prefix,
        )
        if not outline_review_result and cached_outline_review:
            outline_review_result = cached_outline_review

        col_orv, col_oim = st.columns(2)
        if col_orv.button(
            "AI 审查",
            type="primary",
            use_container_width=True,
            disabled=_is_llm_running(),
            key=_widget_key(outline_review_widget_prefix, "run_review"),
        ):
            def work(cancel_event):
                from planning_assist import review_global_outline
                apply_runtime_mode(mock)
                result = review_global_outline(PROJECT_DIR, mock=mock)
                _save_review("outline", _outline_cache_key, result)
                return result

            def done(result):
                st.session_state[outline_review_key] = result
                st.success(f"{outline_subject}审查完成")

            _start_llm_background_job(f"{outline_subject} AI 审查", work, eta_seconds=90, on_success=done)

        edited_outline_review_result = _render_editable_review_text(
            "outline",
            _outline_cache_key,
            outline_review_key,
            outline_review_result,
            "审查报告",
            key_prefix=outline_review_widget_prefix,
        )

        outline_improve_running = _is_llm_running()
        if col_oim.button(
            "根据审查生成改稿",
            use_container_width=True,
            disabled=outline_improve_running,
            key=_widget_key(outline_review_widget_prefix, "run_improve"),
        ):
            if not outline_review_result:
                latest = _load_review("outline", _outline_cache_key)
                if latest:
                    outline_review_result = latest
                    st.session_state[outline_review_key] = latest
                    edited_outline_review_result = latest
                else:
                    st.warning("还没有可用的审查报告。请先运行 AI 审查，完成后点「重新读取审查结果」。")
                    st.stop()
            outline_review_for_improve = (edited_outline_review_result or outline_review_result or "").strip()
            if not outline_review_for_improve:
                st.warning("审查意见为空，无法生成改稿。")
                st.stop()

            def work(cancel_event):
                from planning_assist import improve_global_outline
                apply_runtime_mode(mock)
                path = improve_global_outline(PROJECT_DIR, outline_review_for_improve, mock=mock)
                return str(path.relative_to(PROJECT_DIR))

            _start_llm_background_job(
                f"{outline_subject} AI 改稿",
                work,
                eta_seconds=90,
                on_success=lambda rel: st.success(f"改稿已保存到 AI 草案：{rel}"),
            )

        if not outline_review_result:
            col_oim.caption("先运行「AI 审查」再生成改稿")

        st.divider()
        _render_ai_draft_adoption(
            title="大纲 AI 草案查看 / 采纳",
            source_prefixes=("01_大纲/",),
            empty_hint="暂无大纲 AI 草案。可先在本页生成总纲草案、章纲草案，或运行 AI 审查后生成改稿。",
        )

# ─── 页面：写作（核心） ──────────────────────────────────────────────────────

def page_generate():
    from webui_infra.pages.writing import render as _writing_render
    _writing_render()

def _render_writing_assist(chapter_num: int, mock: bool, key_prefix: str = "writing_assist"):
    ch = ch_str(chapter_num)
    key_base = _widget_key(key_prefix, ch)
    source_rel, current_text = latest_chapter_text(ch)
    mode = st.selectbox("辅助类型", list(WRITING_ASSIST_MODES), key=_widget_key(key_base, "mode"))
    selected_text = st.text_area(
        "片段",
        value="",
        height=180,
        key=_widget_key(key_base, "selection"),
        placeholder="可粘贴要处理的片段；留空时使用当前稿件窗口。",
    )
    request = st.text_area(
        "指令",
        height=120,
        key=_widget_key(key_base, "request"),
        placeholder="例如：把这一段改得更压抑，强化人物想说又没说出口的潜台词。",
    )
    c1, c2 = st.columns([1, 2])
    c1.caption(f"来源：{source_rel or '暂无正文'}")
    if c2.button(
        "生成 inline diff",
        type="primary",
        use_container_width=True,
        disabled=_is_llm_running(),
        key=_widget_key(key_base, "generate_inline_diff"),
    ):
        def work(cancel_event):
            path = run_writing_assist(
                chapter_num,
                mode,
                user_request=request,
                selected_text=selected_text,
                mock=mock,
            )
            if cancel_event.is_set():
                return None
            revised_text = extract_adoptable_assist_text(path.read_text(encoding="utf-8")).strip()
            source_after, original_text = latest_chapter_text(ch)
            if selected_text.strip() and selected_text.strip() in original_text and revised_text:
                candidate_text = original_text.replace(selected_text.strip(), revised_text, 1)
            else:
                candidate_text = revised_text or path.read_text(encoding="utf-8").strip()
            return {
                "ch": ch,
                "source_rel": source_after,
                "original": original_text,
                "revised": candidate_text,
                "title": f"AI 辅助：{mode}",
            }

        def done(result):
            if not result:
                return
            _store_inline_revision_preview(
                result["ch"],
                result["source_rel"],
                result["original"],
                result["revised"],
                result["title"],
            )
            st.success("已生成可逐块裁决的 inline diff。")

        _start_llm_background_job(
            "写作 AI inline diff",
            work,
            eta_seconds=90,
            on_success=done,
        )

    assist_files = sorted(
        (PROJECT_DIR / "04_审核日志").glob(f"第{ch}章_AI辅助_*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if assist_files:
        st.divider()
        with st.expander("历史 AI 输出", expanded=False):
            selected = st.selectbox(
                "历史输出",
                [str(path.relative_to(PROJECT_DIR)).replace("\\", "/") for path in assist_files],
                key=_widget_key(key_base, "history"),
            )
            st.markdown(read_file(selected))
            if st.button(
                "作为 inline diff 预览",
                key=_widget_key(key_base, "preview_history", selected),
                use_container_width=True,
            ):
                try:
                    source_rel, original_text = latest_chapter_text(ch)
                    revised_text = extract_adoptable_assist_text(read_file(selected)).strip()
                    _store_inline_revision_preview(
                        ch,
                        source_rel,
                        original_text,
                        revised_text,
                        f"历史 AI 输出：{Path(selected).name}",
                    )
                    st.success("已放入稿纸上方的 inline diff 预览。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"预览失败：{exc}")


def _store_inline_revision_preview(
    ch: str,
    source_rel: str,
    original_text: str,
    revised_text: str,
    title: str,
) -> None:
    st.session_state[f"_inline_revision_preview_{ch}"] = {
        "source_rel": source_rel,
        "original": original_text,
        "revised": revised_text,
        "title": title,
        "reason": title,
        "decisions": {},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

def _render_assist_candidate_adoption(
    chapter_num: int,
    key_prefix: str,
    title: str = "历史草案采纳",
    show_empty: bool = False,
):
    ch = ch_str(chapter_num)
    candidate_files = list_writing_assist_candidates(chapter_num)
    if not candidate_files:
        if show_empty:
            st.info("暂无可采纳辅助草案。")
        return

    st.divider()
    st.subheader(title)
    selected_candidate = st.selectbox(
        "选择辅助草案",
        [str(path.relative_to(PROJECT_DIR)).replace("\\", "/") for path in candidate_files],
        key=f"{key_prefix}_candidate_{ch}",
    )
    candidate_text = read_file(selected_candidate)
    candidate_key = re.sub(r"[^\w\u4e00-\u9fff]+", "_", selected_candidate)[-90:]
    source_rel, source_text = latest_chapter_text(ch)
    stat_col1, stat_col2, stat_col3 = st.columns(3)
    stat_col1.caption(f"当前稿：{source_rel or '暂无'}")
    stat_col2.caption(f"草案字数：{word_count(candidate_text)}")
    stat_col3.caption(f"文件：{Path(selected_candidate).name}")

    edited_candidate = st.text_area(
        "预览/微调",
        value=candidate_text,
        height=420,
        key=f"{key_prefix}_candidate_edit_{ch}_{candidate_key}",
    )
    with st.expander("与当前稿差异", expanded=False):
        if source_text.strip():
            st.code(
                build_text_diff(source_text, edited_candidate, source_rel or "当前稿件", selected_candidate),
                language="diff",
            )
        else:
            st.info("暂无当前稿件，无法生成差异。")

    with st.expander("采纳前质量对比", expanded=True):
        try:
            comparison = compare_assist_candidate_quality(chapter_num, selected_candidate, edited_candidate)
            st.dataframe(comparison["rows"], use_container_width=True, hide_index=True)
            for warning in comparison["warnings"]:
                st.warning(warning)
            if not comparison["warnings"]:
                st.caption("未发现明显采纳风险，仍建议结合 diff 做最后判断。")
        except Exception as exc:
            st.info(f"暂不能生成质量对比：{exc}")

    save_col, adopt_col = st.columns([1, 1])
    if save_col.button("保存辅助草案修改", key=f"{key_prefix}_save_candidate_{ch}", use_container_width=True):
        try:
            path = _validate_writing_assist_candidate(chapter_num, selected_candidate)
            write_file(_project_rel(path), edited_candidate)
            st.success("辅助草案已保存")
        except Exception as exc:
            st.error(f"保存失败：{exc}")
    confirm_key = f"{key_prefix}_confirm_promote_candidate_{ch}_{candidate_key}"
    confirm = st.checkbox("确认写入修订稿（会备份现有修订稿）", key=confirm_key)
    if adopt_col.button(
        "写入修订稿",
        key=f"{key_prefix}_promote_candidate_{ch}",
        use_container_width=True,
        disabled=not confirm,
    ):
        try:
            revised_path = promote_assist_candidate_to_revision(chapter_num, selected_candidate, edited_candidate)
            st.success(f"已写入：{revised_path.relative_to(PROJECT_DIR)}")
        except Exception as exc:
            st.error(f"写入失败：{exc}")

def _render_quality_radar(report: dict):
    metrics = report.get("metrics", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("章首抓力", f"{int(metrics.get('opening_hook_score', 0))}/100")
    c2.metric("章末余味", f"{int(metrics.get('ending_hook_score', 0))}/100")
    c3.metric("追读张力", f"{int(metrics.get('page_turner_score', 0))}/100")
    c4.metric("文气质地", f"{int(metrics.get('prose_texture_score', 0))}/100")
    c5.metric("读者抓力", f"{int(metrics.get('reader_grip_score', 0))}/100")
    rows = [
        {"维度": "章首抓力", "数值": metrics.get("opening_hook_score", 0), "单位": "分"},
        {"维度": "章末余味", "数值": metrics.get("ending_hook_score", 0), "单位": "分"},
        {"维度": "冲突信号", "数值": metrics.get("conflict_signal_density_per_1k", 0), "单位": "每千字"},
        {"维度": "角色主动性", "数值": metrics.get("agency_signal_density_per_1k", 0), "单位": "每千字"},
        {"维度": "可感细节", "数值": metrics.get("sensory_detail_density_per_1k", 0), "单位": "每千字"},
        {"维度": "身体化情绪", "数值": metrics.get("body_emotion_density_per_1k", 0), "单位": "每千字"},
        {"维度": "异常/线索", "数值": metrics.get("intrigue_signal_density_per_1k", 0), "单位": "每千字"},
        {"维度": "说明性句子", "数值": f"{float(metrics.get('exposition_sentence_ratio', 0)):.1%}", "单位": "占比"},
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

# ─── 流水线执行 ──────────────────────────────────────────────────────────────

def _run_pipeline(chapter_num: int, generate: bool, audit: bool, reader_mirror: bool, quality: bool, mock: bool):
    def work(cancel_event):
        apply_runtime_mode(mock)
        ch = ch_str(chapter_num)
        messages: list[str] = []
        if generate:
            from novel_pipeline import run_full
            run_full(chapter_num, mock=mock)
            return [f"第{chapter_num}章流水线已完成"]

        source, text = latest_chapter_text(ch)
        if not text:
            raise RuntimeError("找不到可处理稿件，请先生成正文")

        if audit:
            from novel_pipeline import run_audit_only
            run_audit_only(chapter_num, mock=mock)
            messages.append("逻辑审计已完成")
        if reader_mirror:
            from llm_router import LLMRouter
            result = LLMRouter(project_dir=PROJECT_DIR).reader_mirror(
                text, read_file("03_滚动记忆/最近摘要.md") or ""
            )
            write_file(f"04_审核日志/第{ch}章_读者镜像.md", result)
            messages.append(f"读者镜像已保存（参考层），来源：{source}")
        if quality:
            from quality_diagnostics import write_quality_diagnostics
            _, _, report = write_quality_diagnostics(PROJECT_DIR, chapter_num, text, source)
            messages.append(f"质量诊断已保存：{report['score']}分，{report['grade']}")
        return messages or ["没有需要执行的操作"]

    def done(messages):
        for message in messages or []:
            st.success(message)

    _start_llm_background_job(
        f"第{chapter_num}章流水线执行",
        work,
        eta_seconds=180 if generate else 75,
        on_success=done,
    )



def _run_feedback_revision(chapter_num: int, mock: bool):
    def work(cancel_event):
        apply_runtime_mode(mock)
        from novel_pipeline import run_revise_from_feedback
        run_revise_from_feedback(chapter_num, mock=mock)
        return f"第{chapter_num}章修订稿与复查已完成"

    _start_llm_background_job(
        f"第{chapter_num}章诊断驱动改稿",
        work,
        eta_seconds=120,
        on_success=lambda message: st.success(message),
    )


def _run_finalize(chapter_num: int, mock: bool):
    def work(cancel_event):
        apply_runtime_mode(mock)
        from novel_pipeline import run_finalize
        run_finalize(chapter_num, yes=True, mock=mock)
        return f"第{chapter_num}章定稿记忆已更新"

    _start_llm_background_job(
        f"第{chapter_num}章定稿记忆更新",
        work,
        eta_seconds=120,
        on_success=lambda message: st.success(message),
    )


def _render_delete_chapter_controls(chapter_num: int, key_prefix: str):
    from chapter_ops import collect_chapter_artifacts, delete_chapter_to_recycle
    from project_center import generate_quality_report

    ch = ch_str(chapter_num)
    artifacts = collect_chapter_artifacts(PROJECT_DIR, chapter_num)
    st.caption(f"会移动 {len(artifacts)} 个文件/目录到 99_回收站，可手动恢复。")
    if artifacts:
        with st.expander("查看将移动的内容"):
            st.dataframe(
                [{"路径": str(path.relative_to(PROJECT_DIR)).replace("\\", "/")} for path in artifacts],
                use_container_width=True,
                hide_index=True,
            )
    reason = st.text_input("删除原因", value="测试章节清理", key=f"{key_prefix}_delete_reason_{ch}")
    if st.button("删除到回收站", use_container_width=True, disabled=not artifacts, key=f"{key_prefix}_delete_button_{ch}"):
        try:
            result = delete_chapter_to_recycle(PROJECT_DIR, chapter_num, reason=reason)
            generate_quality_report(PROJECT_DIR)
            st.success(f"已移动到：{result['recycle_dir']}")
            st.rerun()
        except Exception as exc:
            st.error(f"删除失败：{exc}")


def _scene_workspace(chapter_num: int, mock: bool):
    ch = ch_str(chapter_num)
    plan_rel = f"01_大纲/章纲/第{ch}章_scenes/scene_plan.json"
    col_plan, col_assemble = st.columns(2)
    if col_plan.button("生成/刷新场景计划", use_container_width=True, key=f"plan_scenes_{ch}", disabled=_is_llm_running()):
        def work(cancel_event):
            apply_runtime_mode(mock)
            from llm_router import LLMRouter
            from prompt_assembly import build_axis_context
            from structured_store import sync_scene_plan_from_task_card

            llm = LLMRouter(project_dir=PROJECT_DIR)
            scenes = sync_scene_plan_from_task_card(
                PROJECT_DIR,
                chapter_num,
                llm=llm,
                context=build_axis_context(PROJECT_DIR),
            )
            return f"已生成 {len(scenes)} 个场景"

        _start_llm_background_job(
            f"第{chapter_num}章场景计划",
            work,
            eta_seconds=75,
            on_success=lambda message: st.success(message),
        )
    if col_assemble.button("合并场景为章节草稿", use_container_width=True, key=f"assemble_scenes_{ch}", disabled=_is_llm_running()):
        try:
            from novel_pipeline import run_assemble_scenes
            run_assemble_scenes(chapter_num)
            st.success("已合并为章节草稿")
            st.rerun()
        except SystemExit:
            st.error("合并失败：请确认每个场景都有草稿")
        except Exception as exc:
            st.error(f"合并失败：{exc}")

    if not (PROJECT_DIR / plan_rel).exists():
        st.info("暂无场景计划。先生成场景计划。")
        return

    try:
        scenes = json.loads(read_file(plan_rel))
    except json.JSONDecodeError as exc:
        st.error(f"场景计划 JSON 格式错误：{exc}")
        return

    selected_scene = st.selectbox(
        "选择场景",
        [f"scene_{item['scene_number']:03d}｜{item.get('title', '')}" for item in scenes],
        key=f"scene_select_{ch}",
    )
    scene_number = int(re.search(r"scene_(\d+)", selected_scene).group(1))
    scene = next(item for item in scenes if int(item["scene_number"]) == scene_number)
    from structured_store import list_scene_drafts

    draft_paths = list_scene_drafts(PROJECT_DIR, chapter_num, scene_number)
    draft_rels = [str(path.relative_to(PROJECT_DIR)).replace("\\", "/") for path in draft_paths]
    selected_rel = scene.get("selected_draft_path") or (draft_rels[-1] if draft_rels else "")
    if selected_rel not in draft_rels and draft_rels:
        selected_rel = draft_rels[-1]

    left, right = st.columns([1, 1])
    with left:
        st.subheader("场景计划")
        st.json(scene)
        c1, c2, c3 = st.columns(3)
        if c1.button("生成候选稿", use_container_width=True, key=f"draft_scene_{ch}_{scene_number}", disabled=_is_llm_running()):
            _run_scene_command(chapter_num, scene_number, "draft", mock)
        if c2.button("审稿当前稿", use_container_width=True, key=f"review_scene_{ch}_{scene_number}", disabled=_is_llm_running()):
            _run_scene_command(chapter_num, scene_number, "review", mock)
        if c3.button("生成对比", use_container_width=True, key=f"compare_scene_{ch}_{scene_number}", disabled=_is_llm_running()):
            _run_scene_command(chapter_num, scene_number, "compare", mock)

        if draft_rels:
            picked_rel = st.selectbox(
                "候选稿版本",
                draft_rels,
                index=draft_rels.index(selected_rel) if selected_rel in draft_rels else len(draft_rels) - 1,
                key=f"draft_pick_{ch}_{scene_number}",
            )
            if st.button("选择此稿用于章节合并", use_container_width=True, key=f"select_draft_{ch}_{scene_number}", disabled=_is_llm_running()):
                version_match = re.search(r"_v(\d+)\.md$", picked_rel)
                if not version_match:
                    st.error("候选稿文件名缺少版本号")
                else:
                    _run_scene_command(chapter_num, scene_number, "select", mock, int(version_match.group(1)))
        else:
            picked_rel = ""
            st.info("暂无候选稿。可以先生成一个候选稿。")
    with right:
        draft_rel = picked_rel or selected_rel
        review_rel = f"04_审核日志/第{ch}章_scene_{scene_number:03d}_review.md"
        comparison_rel = f"04_审核日志/第{ch}章_scene_{scene_number:03d}_comparison.md"
        st.subheader("场景草稿")
        draft_text = read_file(draft_rel)
        if draft_text:
            st.caption(f"{word_count(draft_text)} 字 ｜ {draft_rel}")
            st.markdown(draft_text)
        else:
            st.info("暂无场景草稿")
        with st.expander("场景审稿"):
            review_text = read_file(review_rel)
            st.markdown(review_text if review_text else "暂无场景审稿")
        with st.expander("候选稿对比"):
            comparison_text = read_file(comparison_rel)
            st.markdown(comparison_text if comparison_text else "暂无候选稿对比")


def _run_scene_command(chapter_num: int, scene_number: int, action: str, mock: bool, version: int | None = None):
    def work(cancel_event):
        apply_runtime_mode(mock)
        from novel_pipeline import (
            run_compare_scene_drafts,
            run_scene_draft,
            run_scene_review,
            run_select_scene_draft,
        )
        if action == "draft":
            run_scene_draft(chapter_num, scene_number, mock=mock)
            return "场景候选稿已生成"
        if action == "review":
            run_scene_review(chapter_num, scene_number, mock=mock)
            return "场景审稿已生成"
        if action == "compare":
            run_compare_scene_drafts(chapter_num, scene_number)
            return "候选稿对比已生成"
        if action == "select" and version is not None:
            run_select_scene_draft(chapter_num, scene_number, version)
            return "候选稿已选择"
        raise RuntimeError("未知场景动作")

    _start_llm_background_job(
        f"场景 {scene_number} 执行",
        work,
        eta_seconds=90 if action in {"draft", "review"} else 30,
        on_success=lambda message: st.success(message),
        on_error=lambda error: st.error("执行失败：缺少场景计划或候选稿" if "SystemExit" in error else f"执行失败：{error.splitlines()[-1] if error else '未知错误'}"),
    )

# ─── 页面：记忆 ─────────────────────────────────────────────────────────────

def page_memory():
    st.title("滚动记忆")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["全局摘要", "最近摘要", "伏笔追踪", "人物状态", "结构化记忆"])
    pairs = [
        (tab1, "03_滚动记忆/全局摘要.md", "global"),
        (tab2, "03_滚动记忆/最近摘要.md", "recent"),
        (tab3, "03_滚动记忆/伏笔追踪.md", "foreshadow"),
        (tab4, "03_滚动记忆/人物状态表.md", "chars"),
    ]
    for tab, path, key in pairs:
        with tab:
            _md_editor(path, key=f"mem_{key}")
    with tab5:
        memory_dir = PROJECT_DIR / "03_滚动记忆" / "章节记忆"
        memory_files = sorted(memory_dir.glob("*.json")) if memory_dir.exists() else []
        foreshadow_json = PROJECT_DIR / "03_滚动记忆" / "伏笔追踪.json"
        character_json = PROJECT_DIR / "03_滚动记忆" / "人物状态.json"
        left, middle, right = st.columns(3)
        with left:
            st.subheader("章节记忆 JSON")
            if memory_files:
                selected = st.selectbox("选择章节记忆", [str(p.relative_to(PROJECT_DIR)) for p in memory_files])
                st.json(json.loads(read_file(selected)))
            else:
                st.info("暂无章节记忆 JSON，定稿并更新记忆后生成。")
        with middle:
            st.subheader("伏笔 JSON")
            if foreshadow_json.exists():
                st.json(json.loads(foreshadow_json.read_text(encoding="utf-8")))
            else:
                st.info("暂无伏笔 JSON，定稿并更新记忆后生成。")
        with right:
            st.subheader("人物状态 JSON")
            if character_json.exists():
                st.json(json.loads(character_json.read_text(encoding="utf-8")))
            else:
                st.info("暂无人物状态 JSON，定稿并更新记忆后生成。")

# ─── 页面：日志 ─────────────────────────────────────────────────────────────

def page_logs():
    from cost_tracker import build_usage_summary, format_costs
    from project_archive import (
        collect_version_backups,
        create_project_snapshot,
        list_snapshots,
        restore_version_backup,
    )

    st.title("日志")
    tab_calls, tab_cost, tab_versions, tab_snapshots, tab_structured, tab_health = st.tabs(
        ["LLM 调用", "Token费用", "文件备份", "项目快照", "结构化文件", "健康检查"]
    )

    with tab_calls:
        log_path = PROJECT_DIR / "logs" / "llm_calls.jsonl"
        if not log_path.exists():
            st.info("暂无 LLM 调用日志")
        else:
            lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            limit = st.slider("显示最近 N 条", min_value=5, max_value=100, value=20, step=5)
            rows = []
            for line in lines[-limit:]:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    rows.append({"raw": line})
            st.dataframe(rows, use_container_width=True, hide_index=True)
            with st.expander("原始 JSONL 片段"):
                st.code("\n".join(lines[-limit:]), language="json")

    with tab_cost:
        usage = build_usage_summary(PROJECT_DIR)
        totals = usage["totals"]
        st.caption(
            "费用为估算值：DeepSeek 官方平台按人民币计价，并在 usage 返回缓存命中/未命中时分项估算；"
            "Anthropic/OpenRouter 仍按 USD 示例价估算。价格可通过 NOVEL_COST_* 环境变量覆盖。"
        )
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("调用次数", totals["calls"])
        c2.metric("输入 tokens", f"{totals['input_tokens']:,}")
        c3.metric("输出 tokens", f"{totals['output_tokens']:,}")
        c4.metric("总 tokens", f"{totals['total_tokens']:,}")
        c5.metric("估算费用", format_costs(totals))

        model_rows = sorted(usage["by_model"], key=lambda row: row["total_tokens"], reverse=True)
        workflow_rows = sorted(usage["by_workflow"], key=lambda row: row["total_tokens"], reverse=True)
        detail_rows = [
            {
                "timestamp": row.get("timestamp", ""),
                "workflow": row.get("workflow", ""),
                "role": row.get("role", ""),
                "provider": row.get("provider", ""),
                "model": row.get("model", ""),
                "status": row.get("status", ""),
                "input_tokens": row.get("input_tokens", 0),
                "output_tokens": row.get("output_tokens", 0),
                "total_tokens": row.get("total_tokens", 0),
                "cache_hit_tokens": row.get("input_cache_hit_tokens", 0),
                "cache_miss_tokens": row.get("input_cache_miss_tokens", 0),
                "token_source": row.get("token_source", "missing"),
                "currency": row.get("estimated_cost_currency", ""),
                "estimated_cost_cny": row.get("estimated_cost_cny", 0),
                "estimated_cost_usd": row.get("estimated_cost_usd", 0),
            }
            for row in usage["records"]
        ]
        def cost_summary_rows(rows: list[dict]) -> list[dict]:
            output = []
            for row in rows:
                item = {
                    "calls": row.get("calls", 0),
                    "input_tokens": row.get("input_tokens", 0),
                    "output_tokens": row.get("output_tokens", 0),
                    "total_tokens": row.get("total_tokens", 0),
                    "cache_hit_tokens": row.get("input_cache_hit_tokens", 0),
                    "cache_miss_tokens": row.get("input_cache_miss_tokens", 0),
                    "estimated_cost": format_costs(row),
                    "estimated_cost_cny": row.get("estimated_cost_cny", 0),
                    "estimated_cost_usd": row.get("estimated_cost_usd", 0),
                }
                if "provider" in row:
                    item = {"provider": row.get("provider", ""), "model": row.get("model", ""), **item}
                if "workflow" in row:
                    item = {"workflow": row.get("workflow", ""), **item}
                output.append(item)
            return output

        tab_model, tab_workflow, tab_detail = st.tabs(["按模型", "按工作流", "调用明细"])
        with tab_model:
            if model_rows:
                st.dataframe(cost_summary_rows(model_rows), use_container_width=True, hide_index=True)
            else:
                st.info("暂无可统计的模型调用。")
        with tab_workflow:
            if workflow_rows:
                st.dataframe(cost_summary_rows(workflow_rows), use_container_width=True, hide_index=True)
            else:
                st.info("暂无可统计的工作流调用。")
        with tab_detail:
            if detail_rows:
                limit = st.slider("明细最近 N 条", min_value=10, max_value=500, value=100, step=10, key="usage_detail_limit")
                st.dataframe(detail_rows[-limit:], use_container_width=True, hide_index=True)
            else:
                st.info("暂无调用明细。")

    with tab_versions:
        version_rows = collect_version_backups(PROJECT_DIR)
        if not version_rows:
            st.info("暂无备份文件")
        else:
            st.dataframe(version_rows, use_container_width=True, hide_index=True)
            selected = st.selectbox("选择备份文件", [row["rel_path"] for row in version_rows])
            selected_row = next(row for row in version_rows if row["rel_path"] == selected)
            selected_path = PROJECT_DIR / selected
            st.caption(
                f"恢复目标：{selected_row['target_rel_path']} ｜ "
                f"{selected_row['size']} bytes ｜ {selected_row['modified_at']}"
            )
            if selected_path.suffix.lower() in {".md", ".txt", ".json", ".py", ".toml", ".yaml", ".yml"}:
                st.code(read_file(selected), language="json" if selected_path.suffix.lower() == ".json" else "markdown")
            else:
                st.info("该备份不是可直接预览的文本文件。")

            if st.button("恢复此备份到原文件", type="primary"):
                try:
                    result = restore_version_backup(PROJECT_DIR, selected)
                    st.success(f"已恢复：{result['restored']}")
                    if result["current_backup"]:
                        st.caption(f"恢复前的当前文件已备份：{result['current_backup']}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"恢复失败：{exc}")

    with tab_snapshots:
        label = st.text_input("快照标签", value="v1_1", key="snapshot_label")
        if st.button("生成项目快照", type="primary"):
            try:
                result = create_project_snapshot(PROJECT_DIR, label=label)
                st.success(
                    f"项目快照已生成：{result.path.relative_to(PROJECT_DIR)} ｜ "
                    f"{result.file_count} 个文件 ｜ {result.total_bytes} bytes"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"生成失败：{exc}")

        snapshots = list_snapshots(PROJECT_DIR)
        if snapshots:
            st.dataframe(snapshots, use_container_width=True, hide_index=True)
            selected_snapshot = st.selectbox("选择快照", [row["rel_path"] for row in snapshots])
            snapshot_path = PROJECT_DIR / selected_snapshot
            st.caption(f"本机路径：{snapshot_path}")
            prepared_key = "_prepared_snapshot_download"
            if st.button("准备下载所选快照", use_container_width=True, key="prepare_snapshot_download"):
                st.session_state[prepared_key] = selected_snapshot
            if st.session_state.get(prepared_key) == selected_snapshot:
                st.download_button(
                    "下载所选快照",
                    data=snapshot_path.read_bytes(),
                    file_name=snapshot_path.name,
                    mime="application/zip",
                    use_container_width=True,
                )
        else:
            st.info("暂无项目快照")

    with tab_structured:
        json_files = []
        for pattern in [
            "01_大纲/章纲/*_task_card.json",
            "04_审核日志/*.json",
            "03_滚动记忆/**/*.json",
        ]:
            json_files.extend(PROJECT_DIR.glob(pattern))
        json_files = sorted(set(json_files), key=lambda p: p.stat().st_mtime, reverse=True)
        if not json_files:
            st.info("暂无结构化 JSON 文件")
        else:
            selected_json = st.selectbox("选择 JSON 文件", [str(p.relative_to(PROJECT_DIR)) for p in json_files])
            try:
                st.json(json.loads(read_file(selected_json)))
            except json.JSONDecodeError:
                st.code(read_file(selected_json), language="json")

    with tab_health:
        _render_health_panel()

def _render_health_panel() -> None:
    """共用健康面板：检查项表格 + 占位符扫描 + setup_test 按钮。"""
    checks = health_checks()
    st.dataframe(checks, use_container_width=True, hide_index=True)

    blocking = [row for row in checks if row["状态"] != "通过" and row["检查项"] in {"目录与模板", "ChromaDB", "Mock RAG"}]
    warnings = [row for row in checks if row["状态"] != "通过" and row not in blocking]
    if blocking:
        st.error("存在会阻断流程的环境问题，请先处理。")
    elif warnings:
        st.warning("存在非阻断问题；Mock 模式仍可跑通，真实模型或正式生成前建议处理。")
    else:
        st.success("当前环境满足工作台运行要求。")

    st.divider()
    st.subheader("占位符扫描")
    placeholders = scan_placeholders()
    if placeholders:
        st.warning(f"发现 {len(placeholders)} 处待补内容")
        st.dataframe(placeholders, use_container_width=True, hide_index=True)
    else:
        st.success("未发现关键占位符")

    st.divider()
    st.subheader("一键运行 setup_test.py")
    if st.button("运行完整环境检查", type="primary"):
        with st.spinner("正在运行 setup_test.py，Ollama 冷启动时会稍慢..."):
            try:
                result = subprocess.run(
                    [sys.executable, "setup_test.py"],
                    cwd=APP_DIR,
                    text=True,
                    capture_output=True,
                    timeout=300,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode == 0:
                    st.success("setup_test.py 运行通过")
                else:
                    st.error(f"setup_test.py 退出码：{result.returncode}")
                st.code((result.stdout or "") + ("\nSTDERR:\n" + result.stderr if result.stderr else ""), language="text")
            except Exception as exc:
                st.error(f"运行失败：{exc}")


# ─── 页面：健康检查 ─────────────────────────────────────────────────────────

def page_health():
    st.title("健康检查")
    _render_health_panel()

# ─── 页面：项目中台 ─────────────────────────────────────────────────────────

def page_project_center():
    st.title("项目中台")
    from project_center import (
        CLARIFY,
        CONSTITUTION,
        QUALITY,
        SPEC,
        STATUS_JSON,
        TASKS,
        ensure_project_center,
        generate_clarification_questions,
        generate_quality_report,
        generate_writing_tasks,
        run_v1_upgrade,
        write_project_status,
    )

    if st.button("初始化/刷新 V1.0 中台", type="primary"):
        report = run_v1_upgrade(PROJECT_DIR)
        st.success(f"已刷新：{len(report.blockers)} 个阻断项，{len(report.warnings)} 个风险项")
        st.rerun()

    ensure_project_center(PROJECT_DIR)
    report_path = write_project_status(PROJECT_DIR)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    metrics = report.get("metrics", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("章纲", metrics.get("chapter_outlines", 0))
    c2.metric("任务卡", f"{metrics.get('confirmed_task_cards', 0)}/{metrics.get('task_cards', 0)}")
    c3.metric("草稿", metrics.get("drafts", 0))
    c4.metric("定稿", metrics.get("finals", 0))
    c5.metric("占位符", metrics.get("placeholders", 0))

    if report.get("blockers"):
        st.error("当前存在阻断项")
        for item in report["blockers"]:
            st.markdown(f"- {item}")
    elif report.get("warnings"):
        st.warning("当前存在风险项")
        for item in report["warnings"]:
            st.markdown(f"- {item}")
    else:
        st.success("项目级检查通过，可以按章节闭环推进。")

    with st.expander("下一步", expanded=True):
        for item in report.get("next_actions", []):
            st.markdown(f"- {item}")

    tab_start, tab_workflow, tab_docs, tab_linkage, tab_tasks, tab_quality, tab_json = st.tabs(
        ["启动向导", "工作流", "规格文档", "联动检查", "澄清与任务", "质量报告", "状态 JSON"]
    )

    with tab_start:
        _render_startup_wizard()
        st.divider()
        _render_ai_draft_adoption()
        st.divider()
        _render_placeholder_help()

    with tab_workflow:
        workflow = report.get("workflow", [])
        st.dataframe(workflow, use_container_width=True, hide_index=True)

    with tab_docs:
        doc_choice = st.selectbox(
            "选择文档",
            [CONSTITUTION, SPEC],
            format_func=lambda rel: "创作宪法" if rel == CONSTITUTION else "故事规格",
        )
        _md_editor(doc_choice, key=f"project_doc_{doc_choice}", height=520)

    with tab_linkage:
        from prompt_assembly import build_linkage_report
        from project_center import collect_linkage_drift_issues

        linkage = build_linkage_report(PROJECT_DIR)
        axis = linkage.get("axis_present", {})
        cols = st.columns(len(axis) or 1)
        for col, (name, ok) in zip(cols, axis.items()):
            col.metric(name, "已接入" if ok else "待补充")
        if linkage.get("story_spec"):
            st.subheader("故事规格摘要")
            st.markdown(linkage["story_spec"])
        else:
            st.info("故事规格还没有可注入内容。补完后会自动进入世界观、总纲、角色、章纲、正文等 AI 调用。")
        linkage_issues = collect_linkage_drift_issues(PROJECT_DIR)
        if linkage_issues:
            st.subheader("跨文档联动漂移")
            st.warning("总纲、故事规格、卷纲或角色档案存在已声明但未同步的设定；请优先处理，否则正文生成会混用旧设定。")
            st.dataframe(linkage_issues, use_container_width=True, hide_index=True)
        st.subheader("模块联动路径")
        st.dataframe(linkage.get("consumers", []), use_container_width=True, hide_index=True)

    with tab_tasks:
        b1, b2 = st.columns(2)
        if b1.button("生成澄清问题", use_container_width=True):
            generate_clarification_questions(PROJECT_DIR)
            st.success("澄清问题已生成")
            st.rerun()
        if b2.button("生成创作任务", use_container_width=True):
            generate_writing_tasks(PROJECT_DIR)
            st.success("创作任务已生成")
            st.rerun()
        st.divider()
        clarify_col, task_col = st.columns(2)
        with clarify_col:
            st.subheader("澄清问题")
            _md_editor(CLARIFY, key="project_clarify", height=420)
        with task_col:
            st.subheader("创作任务")
            _md_editor(TASKS, key="project_tasks", height=420)

    with tab_quality:
        if st.button("生成质量报告", use_container_width=True):
            generate_quality_report(PROJECT_DIR)
            st.success("质量报告已生成")
            st.rerun()
        st.markdown(read_file(QUALITY))

    with tab_json:
        try:
            st.json(json.loads(read_file(STATUS_JSON)))
        except json.JSONDecodeError:
            st.code(read_file(STATUS_JSON), language="json")


def _render_startup_wizard():
    from onboarding import GENRE_PRESETS, generate_startup_package

    st.subheader("V1.5 启动包")
    cols = st.columns([2, 1, 1])
    inspiration = cols[0].text_area(
        "一句话灵感",
        value="",
        height=100,
        placeholder="例如：一个旧案幸存者收到来自失踪父亲的雨夜来信。",
        key="startup_inspiration",
    )
    genre = cols[1].selectbox("类型预设", list(GENRE_PRESETS), index=list(GENRE_PRESETS).index("悬疑"))
    mock = st.session_state.get("_global_mock", False)
    cols[2].caption(f"运行模式：{'Mock 离线' if mock else prose_model_label(mock)}")
    length_col, pov_col, pace_col = st.columns(3)
    length = length_col.selectbox("篇幅", ["10-30 万字", "30-80 万字", "80-150 万字", "150 万字以上"], index=1)
    pov = pov_col.selectbox("视角", ["第三人称有限视角", "第一人称", "多视角", "全知视角"], index=0)
    pace = pace_col.selectbox("节奏", ["快节奏", "中快节奏", "慢热细腻", "强反转"], index=1)
    with st.expander("类型预设详情", expanded=False):
        st.json(GENRE_PRESETS[genre])
    if st.button(
        "生成启动包",
        type="primary",
        use_container_width=True,
        disabled=not inspiration.strip() or _is_llm_running(),
    ):
        def work(cancel_event):
            apply_runtime_mode(mock)
            result = generate_startup_package(
                PROJECT_DIR,
                inspiration=inspiration,
                genre=genre,
                length=length,
                pov=pov,
                pace=pace,
                mock=mock,
            )
            return {
                "spec": str(result["spec"].relative_to(PROJECT_DIR)),
                "drafts": [str(path.relative_to(PROJECT_DIR)) for path in result["drafts"]],
            }

        def done(result):
            st.success(f"故事规格已写入：{result['spec']}")
            for rel in result["drafts"]:
                st.caption(rel)

        _start_llm_background_job(
            "生成启动包",
            work,
            eta_seconds=180,
            on_success=done,
        )


def _render_ai_draft_adoption(
    title: str = "AI 草案采纳",
    source_prefixes: tuple[str, ...] | None = None,
    empty_hint: str = "暂无 AI 草案。可先在启动向导、世界观 AI 辅助或大纲 AI 辅助中生成。",
    key_prefix: str | None = None,
):
    from onboarding import adopt_ai_draft, delete_ai_draft, list_ai_drafts

    key_prefix = key_prefix or _widget_key("adopt_draft", title, *(source_prefixes or ("all",)))
    st.subheader(title)
    rows = list_ai_drafts(PROJECT_DIR)
    if source_prefixes:
        rows = [row for row in rows if row["source"].startswith(source_prefixes)]
    if not rows:
        st.info(empty_hint)
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)
    selected = st.selectbox("选择草案", [row["source"] for row in rows], key=f"{key_prefix}_select")
    selected_row = next(row for row in rows if row["source"] == selected)
    target = selected_row["target"]

    draft_content = read_file(selected)
    target_content = read_file(target)
    st.caption(f"草案路径：{selected} ｜ 采纳目标：{target} ｜ 更新时间：{selected_row['modified_at']}")
    meta_col1, meta_col2, meta_col3 = st.columns(3)
    meta_col1.metric("草案字数", len(draft_content))
    meta_col2.metric("草案行数", len(draft_content.splitlines()))
    meta_col3.metric("目标状态", "将覆盖" if target_content else "新建")

    st.markdown("#### 草案内容查看")
    view_tab, source_tab, target_tab = st.tabs(["正文阅读", "Markdown 源码", "采纳目标"])
    with view_tab:
        if draft_content.strip():
            st.markdown(draft_content)
        else:
            st.info("草案文件为空。")
    with source_tab:
        st.text_area(
            "草案全文",
            value=draft_content,
            height=520,
            disabled=True,
            key=_widget_key(key_prefix, "source_view", selected),
        )
    with target_tab:
        st.caption(f"采纳后写入：{target}")
        if target_content:
            st.warning("目标文件已存在，采纳时会先备份旧文件再覆盖。")
            st.text_area(
                "当前正式文件内容",
                value=target_content,
                height=420,
                disabled=True,
                key=_widget_key(key_prefix, "target_view", target),
            )
        else:
            st.info("目标文件尚不存在，采纳后会创建新文件。")
    col_adopt, col_delete = st.columns(2)
    with col_adopt:
        if st.button("采纳到正式文件", type="primary", use_container_width=True, key=f"{key_prefix}_adopt"):
            try:
                result = adopt_ai_draft(PROJECT_DIR, selected, target)
                st.success(f"已采纳到：{result.target.relative_to(PROJECT_DIR)}")
                if result.backup:
                    st.caption(f"原文件已备份：{result.backup.relative_to(PROJECT_DIR)}")
                if result.archived:
                    st.caption(f"草案已归档：{result.archived.relative_to(PROJECT_DIR)}")
                st.rerun()
            except Exception as exc:
                st.error(f"采纳失败：{exc}")
    with col_delete:
        delete_reason = st.text_input("删除原因（可选）", key=f"{key_prefix}_delete_reason")
        if st.button("删除选中草案", use_container_width=True, key=f"{key_prefix}_delete"):
            try:
                result = delete_ai_draft(PROJECT_DIR, selected, delete_reason)
                st.success(f"草案已移入回收站：{result.recycled.relative_to(PROJECT_DIR)}")
                st.rerun()
            except Exception as exc:
                st.error(f"删除失败：{exc}")


def _render_placeholder_help():
    from onboarding import placeholder_fix_suggestions

    st.subheader("占位符补全建议")
    rows = placeholder_fix_suggestions(PROJECT_DIR)
    if not rows:
        st.success("未发现关键占位符。")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_style_dossier() -> None:
    st.subheader("文风档案")
    st.caption("这里是唯一的文风入口：选择、维护和调整本书的文风档案；生成、审查和诊断都会读取它。")

    st.markdown("**当前文风档案**")
    try:
        from style_profiles import get_style_profile, style_profile_options
        profile_options = style_profile_options(PROJECT_DIR)
    except Exception:
        get_style_profile = None
        profile_options = {"": "未指定"}
    env_data = read_env()
    current_profile = env_data.get("NOVEL_STYLE_PROFILE", "")
    profile_keys = list(profile_options.keys())
    if current_profile not in profile_keys:
        current_profile = ""
    selected_profile = st.selectbox(
        "本书文风档案",
        profile_keys,
        index=profile_keys.index(current_profile),
        format_func=lambda key: profile_options.get(key, key or "未指定"),
        help="作为全书默认参考；单章任务卡仍可临时覆盖。",
        key="style_dossier_default_profile",
    )
    if selected_profile and get_style_profile:
        active_profile = get_style_profile(selected_profile, project_dir=PROJECT_DIR)
        if active_profile:
            if active_profile.personality_summary:
                st.caption(active_profile.personality_summary)
            if active_profile.valued_traits:
                st.caption(f"珍视：{' · '.join(active_profile.valued_traits)}")
            if active_profile.devalued_traits:
                st.caption(f"不强调：{' · '.join(active_profile.devalued_traits)}")
    else:
        st.info("尚未指定文风档案。可从下方内置档案中选择，或新增一个自定义档案。")
    if st.button("保存为本书文风档案", type="primary", use_container_width=True):
        env_data["NOVEL_STYLE_PROFILE"] = selected_profile
        env_path = write_env(env_data)
        saved_at = datetime.fromtimestamp(env_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        st.success(f"已保存本书文风档案（{saved_at}）")
        st.rerun()

    st.divider()
    _render_style_profile_manager(compact=True)


def _render_style_profile_manager(compact: bool = False) -> None:
    """风格档案管理：查看/新增/编辑/删除 StyleProfile 配置。"""
    st.subheader("文风档案维护")
    if compact:
        st.caption("内置档案可覆盖；自定义档案可增删。当前选中的档案会进入 AI 写作链路。")
    else:
        st.caption("维护文风档案——内置默认可覆盖、不可删除；用户档案可自由增删。")

    from style_profiles import (
        STYLE_PROFILES,
        list_style_profiles,
        delete_user_profile,
    )

    # 加载当前所有档案
    all_profiles = list_style_profiles(PROJECT_DIR)
    builtin_names = set(STYLE_PROFILES.keys())

    # ── 新增档案按钮 ──
    add_key = "_style_profile_add_open"
    if add_key not in st.session_state:
        st.session_state[add_key] = False

    if not st.session_state[add_key]:
        if st.button("新增风格档案", use_container_width=True):
            st.session_state[add_key] = True
            st.rerun()

    if st.session_state[add_key]:
        with st.expander("正在添加……", expanded=True):
            _render_style_profile_edit_form(
                None, builtin_names, is_new=True,
                close_key=add_key,
            )

    # ── 档案列表 ──
    for sp in all_profiles:
        is_builtin = sp.name in builtin_names
        tag = "内置" if is_builtin else "自定义"

        expander_key = f"_sp_exp_{sp.name}"
        if expander_key not in st.session_state:
            st.session_state[expander_key] = False

        with st.expander(f"{sp.display_name}（{sp.name}）· {tag}", expanded=st.session_state[expander_key]):
            # 展示字段
            if sp.author:
                st.caption(f"作家：{sp.author}")
            if sp.personality_summary:
                st.caption(f"人格摘要：{sp.personality_summary}")
            if sp.sample_content.strip():
                with st.expander("样本内容（内联）"):
                    st.text(sp.sample_content[:2000])
            elif sp.sample_file:
                st.caption(f"样本文件：{sp.sample_file}")
                sample = sp.effective_sample(PROJECT_DIR)
                if sample:
                    with st.expander("样本内容（文件）"):
                        st.text(sample[:2000])
            if sp.valued_traits:
                st.caption(f"珍视：{' · '.join(sp.valued_traits)}")
            if sp.devalued_traits:
                st.caption(f"不强调：{' · '.join(sp.devalued_traits)}")
            st.caption(f"追读权重：{sp.page_turner_weight:g} ｜ 文气权重：{sp.texture_weight:g}")
            if sp.cliche_overrides:
                with st.expander("套话覆盖"):
                    for term, cfg in sp.cliche_overrides.items():
                        st.caption(f"· 「{term}」→ {cfg}")

            col_edit, col_del = st.columns([1, 1])
            # 编辑按钮
            if col_edit.button("编辑", key=f"_edit_{sp.name}"):
                st.session_state[expander_key] = True
                st.session_state[f"_edit_open_{sp.name}"] = True

            # 删除按钮（仅自定义档案可删）
            if not is_builtin:
                if col_del.button("删除", key=f"_del_{sp.name}"):
                    ok = delete_user_profile(PROJECT_DIR, sp.name)
                    if ok:
                        st.success(f"已删除「{sp.display_name}」")
                        st.rerun()
                    else:
                        st.error("删除失败")

            # 编辑表单
            edit_open_key = f"_edit_open_{sp.name}"
            if edit_open_key not in st.session_state:
                st.session_state[edit_open_key] = False
            if st.session_state[edit_open_key]:
                with st.container():
                    st.markdown("---")
                    _render_style_profile_edit_form(
                        sp, builtin_names, is_new=False,
                        close_key=edit_open_key,
                    )


def _render_style_profile_edit_form(
    profile,            # StyleProfile | None
    builtin_names,      # set[str]
    is_new,             # bool
    close_key,          # str
):
    """单个 StyleProfile 的编辑/新增表单。"""
    from style_profiles import StyleProfile, save_user_profile

    name_val = profile.name if profile else ""
    display_name_val = profile.display_name if profile else ""
    author_val = profile.author if profile else ""
    personality_val = profile.personality_summary if profile else ""
    sample_content_val = profile.sample_content if profile else ""
    valued_val = "、".join(profile.valued_traits) if profile else ""
    devalued_val = "、".join(profile.devalued_traits) if profile else ""
    pt_weight = profile.page_turner_weight if profile else 1.0
    tex_weight = profile.texture_weight if profile else 1.0

    action_label = "新增" if is_new else "保存"

    with st.form(key=f"_sp_form_{name_val or 'new'}"):
        new_name = st.text_input("档案名（name）", value=name_val,
                                 help="英文标识，如 jin_yong、wang_xiaobo",
                                 disabled=not is_new)
        new_display = st.text_input("显示名（display_name）", value=display_name_val,
                                    help="如「金庸路线」")
        new_author = st.text_input("作家姓名", value=author_val)
        new_personality = st.text_area("人格摘要", value=personality_val,
                                       help="一两句话概括作家风格核心，会注入写作 prompt")
        new_sample = st.text_area("样本内容（留空则使用样本文件）",
                                  value=sample_content_val, height=200,
                                  help="直接粘贴作家作品原文选段。优先于样本文件使用。")
        new_valued = st.text_input("珍视特质", value=valued_val,
                                   help="用中文顿号分隔，如：短句、白描、动作叙事")
        new_devalued = st.text_input("不强调特质", value=devalued_val,
                                     help="用中文顿号分隔，如：长句、意识流、意象密集")
        col_pt, col_tex = st.columns(2)
        new_pt = col_pt.number_input("追读权重", value=pt_weight,
                                     min_value=0.0, max_value=2.0, step=0.05)
        new_tex = col_tex.number_input("文气权重", value=tex_weight,
                                       min_value=0.0, max_value=2.0, step=0.05)

        col_save, col_cancel = st.columns([1, 1])
        if col_save.form_submit_button(action_label, type="primary"):
            if not new_name.strip():
                st.error("档案名不能为空")
            else:
                sp = StyleProfile(
                    name=new_name.strip(),
                    display_name=new_display.strip(),
                    author=new_author.strip(),
                    personality_summary=new_personality.strip(),
                    sample_content=new_sample,
                    valued_traits=[t.strip() for t in new_valued.split("、") if t.strip()],
                    devalued_traits=[t.strip() for t in new_devalued.split("、") if t.strip()],
                    page_turner_weight=new_pt,
                    texture_weight=new_tex,
                )
                save_user_profile(PROJECT_DIR, sp)
                st.session_state[close_key] = False
                st.success(f"已保存「{sp.display_name}」")
                st.rerun()

        if col_cancel.form_submit_button("取消"):
            st.session_state[close_key] = False
            st.rerun()


# ─── 页面：设置 ─────────────────────────────────────────────────────────────

def page_settings():
    st.title("设置")

    env_data = read_env()
    active_provider_names = {
        env_data.get("NOVEL_PROSE_PROVIDER", "anthropic"),
        env_data.get("NOVEL_ASSIST_PROVIDER", "anthropic"),
        env_data.get("NOVEL_REVISE_PROVIDER", "anthropic"),
        env_data.get("NOVEL_CRITIC_PROVIDER", "deepseek"),
    }

    st.subheader("连接状态")
    st.caption("这里只显示当前角色路由实际会用到的供应商；其它供应商在下方「暂未启用」里。")
    anthropic_key = env_data.get("ANTHROPIC_API_KEY", "")
    deepseek_key = env_data.get("DEEPSEEK_API_KEY", "")
    openrouter_key = env_data.get("OPENROUTER_API_KEY", "")
    custom_key = env_data.get("NOVEL_CUSTOM_API_KEY", "")
    active_provider_order = [name for name in ["anthropic", "deepseek", "openrouter", "custom"] if name in active_provider_names]
    if active_provider_order:
        key_cols = st.columns(min(4, len(active_provider_order)))
        for idx, provider_name in enumerate(active_provider_order):
            col = key_cols[idx % len(key_cols)]
            if provider_name == "anthropic":
                anthropic_key = col.text_input("Anthropic API Key", value=anthropic_key, type="password", key="active_anthropic_key")
            elif provider_name == "deepseek":
                deepseek_key = col.text_input("DeepSeek API Key", value=deepseek_key, type="password", key="active_deepseek_key")
            elif provider_name == "openrouter":
                openrouter_key = col.text_input("OpenRouter API Key", value=openrouter_key, type="password", key="active_openrouter_key")
            elif provider_name == "custom":
                custom_key = col.text_input("通用接口 API Key", value=custom_key, type="password", key="active_custom_key")
    if "anthropic" in active_provider_names:
        _render_provider_status("anthropic", anthropic_key, env_data.get("NOVEL_CLAUDE_MODEL", "claude-opus-4-6"))
    if "deepseek" in active_provider_names:
        _render_provider_status("deepseek", deepseek_key, env_data.get("NOVEL_DEEPSEEK_MODEL", "deepseek-v4-pro"))
    if "openrouter" in active_provider_names:
        _render_provider_status(
            "openrouter",
            openrouter_key,
            env_data.get("NOVEL_OPENROUTER_PROSE_MODEL", "openrouter/auto"),
            base_url=env_data.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            referer=env_data.get("OPENROUTER_HTTP_REFERER", ""),
            title=env_data.get("OPENROUTER_X_TITLE", "Novel Writing System"),
        )
    if "custom" in active_provider_names:
        _render_provider_status(
            "custom",
            custom_key,
            env_data.get("NOVEL_CUSTOM_PROSE_MODEL", env_data.get("NOVEL_CUSTOM_MODEL", "")),
            base_url=env_data.get("NOVEL_CUSTOM_BASE_URL", ""),
        )
    inactive_providers = [name for name in ["anthropic", "deepseek", "openrouter", "custom"] if name not in active_provider_names]
    if inactive_providers:
        with st.expander("暂未启用供应商", expanded=False):
            st.caption("切换角色路由后，对应供应商会自动移到上方。这里可提前填写 Key。")
            inactive_cols = st.columns(min(4, len(inactive_providers)))
            for idx, provider_name in enumerate(inactive_providers):
                col = inactive_cols[idx % len(inactive_cols)]
                if provider_name == "anthropic":
                    anthropic_key = col.text_input("Anthropic API Key", value=anthropic_key, type="password", key="inactive_anthropic_key")
                elif provider_name == "deepseek":
                    deepseek_key = col.text_input("DeepSeek API Key", value=deepseek_key, type="password", key="inactive_deepseek_key")
                elif provider_name == "openrouter":
                    openrouter_key = col.text_input("OpenRouter API Key", value=openrouter_key, type="password", key="inactive_openrouter_key")
                elif provider_name == "custom":
                    custom_key = col.text_input("通用接口 API Key", value=custom_key, type="password", key="inactive_custom_key")

    with st.form("settings_form", clear_on_submit=False):
        st.caption("参数输入框里按 Enter 会提交并保存整组配置。")
        st.subheader("模型与运行模式")
        try:
            from style_profiles import style_profile_options
            profile_options = style_profile_options(PROJECT_DIR)
        except Exception:
            profile_options = {"": "未指定"}
        current_profile = env_data.get("NOVEL_STYLE_PROFILE", "")
        profile_keys = list(profile_options.keys())
        if current_profile not in profile_keys:
            current_profile = ""
        profile_col, llm_col, rag_col = st.columns([2, 1, 1])
        selected_style_profile = profile_col.selectbox(
            "本书文风档案",
            profile_keys,
            index=profile_keys.index(current_profile),
            format_func=lambda key: profile_options.get(key, key or "未指定"),
            help="与「笔记 → 文风档案」使用同一个配置；影响正文样本注入、诊断阈值和套话容忍度。单章任务卡可覆盖。",
        )
        mode_options = ["auto", "mock", "real"]
        llm_mode = llm_col.selectbox(
            "NOVEL_LLM_MODE",
            mode_options,
            index=mode_options.index(env_data.get("NOVEL_LLM_MODE", "auto"))
            if env_data.get("NOVEL_LLM_MODE", "auto") in mode_options else 0,
            help="auto：有 Key 则真实调用，缺失则 Mock；mock：永不外调；real：缺 Key 直接报错。",
        )
        rag_mode_options = ["auto", "mock"]
        rag_mode = rag_col.selectbox(
            "NOVEL_RAG_MODE",
            rag_mode_options,
            index=rag_mode_options.index(env_data.get("NOVEL_RAG_MODE", "auto"))
            if env_data.get("NOVEL_RAG_MODE", "auto") in rag_mode_options else 0,
            help="auto：优先真实 embedding，失败退回 hash；mock：直接使用 hash embedding。",
        )
        # ── 预加载所有 per-role 默认值 ──────────────────────────────────────
        _or_prose_def  = env_data.get("NOVEL_OPENROUTER_PROSE_MODEL",  "openrouter/auto")
        _or_assist_def = env_data.get("NOVEL_OPENROUTER_ASSIST_MODEL", "openrouter/auto")
        _or_revise_def = env_data.get("NOVEL_OPENROUTER_REVISE_MODEL", "openrouter/auto")
        _or_critic_def = env_data.get("NOVEL_OPENROUTER_CRITIC_MODEL", "openrouter/auto")
        _cu_model_def  = env_data.get("NOVEL_CUSTOM_MODEL", "").strip()
        _cu_prose_def  = env_data.get("NOVEL_CUSTOM_PROSE_MODEL",  _cu_model_def)
        _cu_assist_def = env_data.get("NOVEL_CUSTOM_ASSIST_MODEL", _cu_model_def)
        _cu_revise_def = env_data.get("NOVEL_CUSTOM_REVISE_MODEL", _cu_model_def)
        _cu_critic_def = env_data.get("NOVEL_CUSTOM_CRITIC_MODEL", _cu_model_def)
        reasoning_options = ["max", "high", "medium", "low"]
        deepseek_reasoning = env_data.get("NOVEL_DEEPSEEK_REASONING_EFFORT", "max")
        if deepseek_reasoning not in reasoning_options:
            deepseek_reasoning = "max"
        thinking_options = ["enabled", "disabled"]
        deepseek_thinking = env_data.get("NOVEL_DEEPSEEK_THINKING", "enabled")
        if deepseek_thinking not in thinking_options:
            deepseek_thinking = "enabled"
        # 输出变量兜底（未选对应 provider 时保留 env 值）
        openrouter_prose_model  = _or_prose_def
        openrouter_assist_model = _or_assist_def
        openrouter_revise_model = _or_revise_def
        openrouter_critic_model = _or_critic_def
        custom_prose_model  = _cu_prose_def
        custom_assist_model = _cu_assist_def
        custom_revise_model = _cu_revise_def
        custom_critic_model = _cu_critic_def

        # ── 四角色路由：每列 = 一个角色，先选 provider 再配该角色的模型 ───
        _all_providers = ["anthropic", "openrouter", "deepseek", "custom"]
        st.caption("每个角色独立选择供应商与模型，互不影响。")
        p_col, a_col, r_col, c_col = st.columns(4)

        with p_col:
            _cur = env_data.get("NOVEL_PROSE_PROVIDER", "anthropic")
            prose_provider = st.selectbox(
                "写 · NOVEL_PROSE_PROVIDER", _all_providers,
                index=_all_providers.index(_cur) if _cur in _all_providers else 0,
                help="正文生成（写作）使用的供应商。",
            )
            if prose_provider == "openrouter":
                openrouter_prose_model = st.text_input(
                    "模型 · NOVEL_OPENROUTER_PROSE_MODEL",
                    value=normalize_openrouter_model_id(_or_prose_def),
                    help="只填 claude-... 会自动补 anthropic/ 前缀。",
                )
                _n = normalize_openrouter_model_id(openrouter_prose_model)
                if _n != openrouter_prose_model.strip():
                    st.caption(f"保存后使用：{_n}")
            elif prose_provider == "custom":
                custom_prose_model = st.text_input(
                    "模型 · NOVEL_CUSTOM_PROSE_MODEL", value=_cu_prose_def or _cu_model_def,
                )

        with a_col:
            _cur = env_data.get("NOVEL_ASSIST_PROVIDER", "anthropic")
            assist_provider = st.selectbox(
                "策 · NOVEL_ASSIST_PROVIDER", _all_providers,
                index=_all_providers.index(_cur) if _cur in _all_providers else 0,
                help="策划辅助（世界观/总纲/角色/章纲草案生成与审查）使用的供应商。",
            )
            if assist_provider == "openrouter":
                openrouter_assist_model = st.text_input(
                    "模型 · NOVEL_OPENROUTER_ASSIST_MODEL",
                    value=normalize_openrouter_model_id(_or_assist_def),
                )
                _n = normalize_openrouter_model_id(openrouter_assist_model)
                if _n != openrouter_assist_model.strip():
                    st.caption(f"保存后使用：{_n}")
            elif assist_provider == "custom":
                custom_assist_model = st.text_input(
                    "模型 · NOVEL_CUSTOM_ASSIST_MODEL", value=_cu_assist_def or _cu_model_def,
                )

        with r_col:
            _cur = env_data.get("NOVEL_REVISE_PROVIDER", "anthropic")
            revise_provider = st.selectbox(
                "改 · NOVEL_REVISE_PROVIDER", _all_providers,
                index=_all_providers.index(_cur) if _cur in _all_providers else 0,
                help="修订改稿（审后重写、策划改稿）使用的供应商。",
            )
            if revise_provider == "openrouter":
                openrouter_revise_model = st.text_input(
                    "模型 · NOVEL_OPENROUTER_REVISE_MODEL",
                    value=normalize_openrouter_model_id(_or_revise_def),
                )
                _n = normalize_openrouter_model_id(openrouter_revise_model)
                if _n != openrouter_revise_model.strip():
                    st.caption(f"保存后使用：{_n}")
            elif revise_provider == "custom":
                custom_revise_model = st.text_input(
                    "模型 · NOVEL_CUSTOM_REVISE_MODEL", value=_cu_revise_def or _cu_model_def,
                )

        with c_col:
            _cur = env_data.get("NOVEL_CRITIC_PROVIDER", "deepseek")
            critic_provider = st.selectbox(
                "审 · NOVEL_CRITIC_PROVIDER", _all_providers,
                index=_all_providers.index(_cur) if _cur in _all_providers else 0,
                help="逻辑审计与审查（正文审计、世界观/大纲/角色审查）使用的供应商。",
            )
            if critic_provider == "openrouter":
                openrouter_critic_model = st.text_input(
                    "模型 · NOVEL_OPENROUTER_CRITIC_MODEL",
                    value=normalize_openrouter_model_id(_or_critic_def),
                )
                _n = normalize_openrouter_model_id(openrouter_critic_model)
                if _n != openrouter_critic_model.strip():
                    st.caption(f"保存后使用：{_n}")
            elif critic_provider == "custom":
                custom_critic_model = st.text_input(
                    "模型 · NOVEL_CUSTOM_CRITIC_MODEL", value=_cu_critic_def or _cu_model_def,
                )

        active_route_providers = {prose_provider, assist_provider, revise_provider, critic_provider}


        # ── AI 推进环节独立配置 ──
        st.divider()
        st.subheader("AI 推进环节细分模型配置")
        st.caption("针对 AI 自动推进工作流的各个具体环节，覆盖上方的全局角色配置（留空则继承全局）。")
        with st.expander("展开环节细分配置", expanded=False):
            stages = {
                "outline": "大纲与策划 (生成章纲/世界观/角色)",
                "task": "任务卡 (任务与大纲核对)",
                "scene": "场景计划 (拆解场景)",
                "draft": "正文草稿 (正文生成)",
                "audit": "逻辑审计 (逻辑一致性检查)",
                "mirror": "读者镜像 (情感推演，参考层)",
                "quality": "质量诊断 (规则级质量把控)",
                "drama": "戏剧诊断 (压力/弧光/画面打分)",
                "literary": "文学批评 (人味保护层)",
                "style_court": "风格法庭 (诊断冲突裁决)",
                "revise": "修订改稿 (综合审查意见改写)",
                "finalize": "定稿收尾 (伏笔/状态提取)",
            }
            
            stage_configs = {}
            for stage_key, stage_label in stages.items():
                st.markdown(f"**{stage_label}**")
                s_col1, s_col2 = st.columns([1, 2])
                
                prov_val = env_data.get(f"NOVEL_STAGE_{stage_key.upper()}_PROVIDER", "")
                mod_val = env_data.get(f"NOVEL_STAGE_{stage_key.upper()}_MODEL", "")
                
                sel_prov = s_col1.selectbox(
                    f"供应商 ({stage_key})", 
                    ["(继承全局)", "anthropic", "deepseek", "openrouter", "custom"], 
                    index=["", "anthropic", "deepseek", "openrouter", "custom"].index(prov_val) if prov_val in ["anthropic", "deepseek", "openrouter", "custom"] else 0,
                    key=f"stage_prov_{stage_key}"
                )
                sel_mod = s_col2.text_input(
                    f"指定模型 ({stage_key})", 
                    value=mod_val,
                    placeholder="留空继承上方配置",
                    key=f"stage_mod_{stage_key}"
                )
                stage_configs[f"NOVEL_STAGE_{stage_key.upper()}_PROVIDER"] = sel_prov if sel_prov != "(继承全局)" else ""
                stage_configs[f"NOVEL_STAGE_{stage_key.upper()}_MODEL"] = sel_mod.strip()
                
    
        # ── 供应商连接参数（API 接入 + 共享模型，不含 per-role 配置）────────
        st.subheader("供应商连接参数")
        st.caption("各供应商的接入与共享模型设置，只显示上方已选用的供应商。")

        claude_model = env_data.get("NOVEL_CLAUDE_MODEL", "claude-opus-4-6")
        claude_max_tokens = int(env_data.get("NOVEL_CLAUDE_MAX_TOKENS", "8000") or 8000)
        claude_temperature = float(env_data.get("NOVEL_CLAUDE_TEMPERATURE", "0.85") or 0.85)
        if "anthropic" in active_route_providers:
            st.markdown("**Anthropic**")
            a_model, a_max, a_temp = st.columns([2, 1, 1])
            claude_model = a_model.text_input("模型 · NOVEL_CLAUDE_MODEL", value=claude_model)
            claude_max_tokens = a_max.number_input(
                "最大输出 · NOVEL_CLAUDE_MAX_TOKENS",
                min_value=512, max_value=200000, value=claude_max_tokens, step=512,
            )
            claude_temperature = a_temp.number_input(
                "温度 · NOVEL_CLAUDE_TEMPERATURE",
                min_value=0.0, max_value=2.0, value=claude_temperature, step=0.05,
            )

        deepseek_model = env_data.get("NOVEL_DEEPSEEK_MODEL", "deepseek-v4-pro")
        deepseek_max_tokens = int(env_data.get("NOVEL_DEEPSEEK_MAX_TOKENS", "32000") or 32000)
        if "deepseek" in active_route_providers:
            st.markdown("**DeepSeek**")
            st.caption("模型/max_tokens/推理强度/思考模式 对所有走 DeepSeek 的角色全局生效。")
            d_model, d_max = st.columns([2, 1])
            deepseek_model = d_model.text_input("模型 · NOVEL_DEEPSEEK_MODEL", value=deepseek_model)
            deepseek_max_tokens = d_max.number_input(
                "最大输出 · NOVEL_DEEPSEEK_MAX_TOKENS",
                min_value=1024, max_value=200000, value=deepseek_max_tokens, step=1024,
            )
            d_reason, d_think = st.columns(2)
            deepseek_reasoning = d_reason.selectbox(
                "推理强度 · NOVEL_DEEPSEEK_REASONING_EFFORT",
                reasoning_options,
                index=reasoning_options.index(deepseek_reasoning),
            )
            deepseek_thinking = d_think.selectbox(
                "思考模式 · NOVEL_DEEPSEEK_THINKING",
                thinking_options,
                index=thinking_options.index(deepseek_thinking),
            )

        openrouter_base_url = env_data.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        openrouter_referer = env_data.get("OPENROUTER_HTTP_REFERER", "")
        openrouter_title = env_data.get("OPENROUTER_X_TITLE", "Novel Writing System")
        if "openrouter" in active_route_providers:
            st.markdown("**OpenRouter**")
            or_base_col, or_ref_col, or_title_col = st.columns([2, 1, 1])
            openrouter_base_url = or_base_col.text_input("Base URL · OPENROUTER_BASE_URL", value=openrouter_base_url)
            openrouter_referer = or_ref_col.text_input("HTTP Referer · OPENROUTER_HTTP_REFERER", value=openrouter_referer)
            openrouter_title = or_title_col.text_input("应用标题 · OPENROUTER_X_TITLE", value=openrouter_title)

        custom_provider_name = env_data.get("NOVEL_CUSTOM_PROVIDER_NAME", "通用接口")
        custom_base_url = normalize_custom_base_url(env_data.get("NOVEL_CUSTOM_BASE_URL", ""))
        custom_model = env_data.get("NOVEL_CUSTOM_MODEL", "")
        if "custom" in active_route_providers:
            st.markdown("**通用 OpenAI-Compatible 接口**")
            st.caption("适用于提供 /chat/completions 的供应商，例如 SiliconFlow、Moonshot、智谱、百炼、One API、LiteLLM。")
            cp_name_col, cp_url_col, cp_model_col = st.columns([1, 2, 1.4])
            custom_provider_name = cp_name_col.text_input("供应商名称 · NOVEL_CUSTOM_PROVIDER_NAME", value=custom_provider_name)
            custom_base_url = cp_url_col.text_input(
                "Base URL · NOVEL_CUSTOM_BASE_URL", value=custom_base_url,
                placeholder="https://api.example.com/v1",
                help="填写 OpenAI-compatible base URL，不要包含 /chat/completions。",
            )
            custom_model = cp_model_col.text_input(
                "兜底模型 · NOVEL_CUSTOM_MODEL", value=custom_model,
                help="四个角色模型为空时使用它。",
            )
            custom_url_hint = custom_base_url_warning(custom_base_url)
            if custom_url_hint:
                st.warning(custom_url_hint)

        hidden_providers = [name for name in ["anthropic", "deepseek", "openrouter", "custom"] if name not in active_route_providers]
        if hidden_providers:
            labels = {"anthropic": "Anthropic", "deepseek": "DeepSeek", "openrouter": "OpenRouter", "custom": "通用接口"}
            with st.expander("未启用的大模型设置", expanded=False):
                st.caption("已隐藏：" + "、".join(labels[name] for name in hidden_providers) + "。切换上方角色路由后会自动显示。")

        st.subheader("本地与检索")
        local_model_col, local_url_col = st.columns([1, 2])
        ollama_model = local_model_col.text_input("本地摘要模型 · NOVEL_OLLAMA_MODEL", value=env_data.get("NOVEL_OLLAMA_MODEL", "qwen3:8b"))
        ollama_url = local_url_col.text_input("Ollama 地址 · NOVEL_OLLAMA_URL", value=env_data.get("NOVEL_OLLAMA_URL", "http://localhost:11434/api/generate"))
        o_timeout, o_predict, o_temp, o_top_p = st.columns(4)
        ollama_timeout = o_timeout.number_input(
            "NOVEL_OLLAMA_TIMEOUT",
            min_value=5,
            max_value=1800,
            value=int(env_data.get("NOVEL_OLLAMA_TIMEOUT", "120") or 120),
            step=5,
        )
        ollama_num_predict = o_predict.number_input(
            "NOVEL_OLLAMA_NUM_PREDICT",
            min_value=16,
            max_value=32768,
            value=int(env_data.get("NOVEL_OLLAMA_NUM_PREDICT", "1024") or 1024),
            step=64,
        )
        ollama_temperature = o_temp.number_input(
            "NOVEL_OLLAMA_TEMPERATURE",
            min_value=0.0,
            max_value=2.0,
            value=float(env_data.get("NOVEL_OLLAMA_TEMPERATURE", "0.2") or 0.2),
            step=0.05,
        )
        ollama_top_p = o_top_p.number_input(
            "NOVEL_OLLAMA_TOP_P",
            min_value=0.0,
            max_value=1.0,
            value=float(env_data.get("NOVEL_OLLAMA_TOP_P", "0.9") or 0.9),
            step=0.05,
        )
        openai_timeout_col, custom_retry_input_col, custom_retry_output_col, embed_col = st.columns([1, 1, 1, 2])
        openai_timeout = openai_timeout_col.number_input(
            "NOVEL_OPENAI_TIMEOUT_SECONDS",
            min_value=30,
            max_value=1800,
            value=int(float(env_data.get("NOVEL_OPENAI_TIMEOUT_SECONDS", env_data.get("NOVEL_OPENAI_TIMEOUT", "120")) or 120)),
            step=30,
            help="DeepSeek、OpenRouter 和通用 OpenAI-compatible 接口的请求超时。卷纲、总纲这类长任务建议 300-600 秒。",
        )
        custom_retry_input_limit = custom_retry_input_col.number_input(
            "NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT",
            min_value=8000,
            max_value=120000,
            value=int(env_data.get("NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT", "24000") or 24000),
            step=2000,
            help="通用接口遇到 524/blocked 时，自动压缩重试的输入字符上限。网站网关不稳时可调低。",
        )
        custom_retry_max_tokens = custom_retry_output_col.number_input(
            "NOVEL_CUSTOM_RETRY_MAX_TOKENS",
            min_value=1200,
            max_value=30000,
            value=int(env_data.get("NOVEL_CUSTOM_RETRY_MAX_TOKENS", "6000") or 6000),
            step=1000,
            help="通用接口压缩重试时的输出上限。网站网关 120 秒超时时可调低。",
        )
        embed_model = embed_col.text_input("NOVEL_EMBED_MODEL", value=env_data.get("NOVEL_EMBED_MODEL", r"D:\huggingface\bge-m3"))
    
        if st.form_submit_button("保存配置", type="primary"):
            saved_openrouter_prose_model = (
                normalize_openrouter_model_id(openrouter_prose_model)
                if prose_provider == "openrouter"
                else openrouter_prose_model.strip()
            )
            saved_openrouter_assist_model = (
                normalize_openrouter_model_id(openrouter_assist_model)
                if assist_provider == "openrouter"
                else openrouter_assist_model.strip()
            )
            saved_openrouter_revise_model = (
                normalize_openrouter_model_id(openrouter_revise_model)
                if revise_provider == "openrouter"
                else openrouter_revise_model.strip()
            )
            saved_openrouter_critic_model = (
                normalize_openrouter_model_id(openrouter_critic_model)
                if critic_provider == "openrouter"
                else openrouter_critic_model.strip()
            )
            env_data.update({
                **stage_configs,
                "ANTHROPIC_API_KEY": anthropic_key,
                "DEEPSEEK_API_KEY": deepseek_key,
                "OPENROUTER_API_KEY": openrouter_key,
                "NOVEL_CUSTOM_API_KEY": custom_key,
                "NOVEL_PROSE_PROVIDER": prose_provider,
                "NOVEL_ASSIST_PROVIDER": assist_provider,
                "NOVEL_REVISE_PROVIDER": revise_provider,
                "NOVEL_CRITIC_PROVIDER": critic_provider,
                "NOVEL_CLAUDE_MODEL": claude_model,
                "NOVEL_CLAUDE_MAX_TOKENS": str(claude_max_tokens),
                "NOVEL_CLAUDE_TEMPERATURE": str(claude_temperature),
                "NOVEL_DEEPSEEK_MODEL": deepseek_model,
                "NOVEL_DEEPSEEK_MAX_TOKENS": str(deepseek_max_tokens),
                "NOVEL_DEEPSEEK_REASONING_EFFORT": deepseek_reasoning,
                "NOVEL_DEEPSEEK_THINKING": deepseek_thinking,
                "OPENROUTER_BASE_URL": openrouter_base_url,
                "NOVEL_OPENROUTER_PROSE_MODEL": saved_openrouter_prose_model,
                "NOVEL_OPENROUTER_ASSIST_MODEL": saved_openrouter_assist_model,
                "NOVEL_OPENROUTER_REVISE_MODEL": saved_openrouter_revise_model,
                "NOVEL_OPENROUTER_CRITIC_MODEL": saved_openrouter_critic_model,
                "OPENROUTER_HTTP_REFERER": openrouter_referer,
                "OPENROUTER_X_TITLE": openrouter_title,
                "NOVEL_CUSTOM_PROVIDER_NAME": custom_provider_name,
                "NOVEL_CUSTOM_BASE_URL": normalize_custom_base_url(custom_base_url),
                "NOVEL_CUSTOM_MODEL": custom_model.strip(),
                "NOVEL_CUSTOM_PROSE_MODEL": custom_prose_model.strip(),
                "NOVEL_CUSTOM_ASSIST_MODEL": custom_assist_model.strip(),
                "NOVEL_CUSTOM_REVISE_MODEL": custom_revise_model.strip(),
                "NOVEL_CUSTOM_CRITIC_MODEL": custom_critic_model.strip(),
                "NOVEL_OLLAMA_MODEL": ollama_model,
                "NOVEL_OLLAMA_URL": ollama_url,
                "NOVEL_OLLAMA_TIMEOUT": str(ollama_timeout),
                "NOVEL_OLLAMA_NUM_PREDICT": str(ollama_num_predict),
                "NOVEL_OLLAMA_TEMPERATURE": str(ollama_temperature),
                "NOVEL_OLLAMA_TOP_P": str(ollama_top_p),
                "NOVEL_OPENAI_TIMEOUT_SECONDS": str(openai_timeout),
                "NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT": str(custom_retry_input_limit),
                "NOVEL_CUSTOM_RETRY_MAX_TOKENS": str(custom_retry_max_tokens),
                "NOVEL_LLM_MODE": llm_mode,
                "NOVEL_RAG_MODE": rag_mode,
                "NOVEL_STYLE_PROFILE": selected_style_profile,
                "NOVEL_EMBED_MODEL": embed_model,
                "HF_ENDPOINT": env_data.get("HF_ENDPOINT", "https://hf-mirror.com"),
                "HF_HUB_DISABLE_XET": env_data.get("HF_HUB_DISABLE_XET", "1"),
            })
            env_path = write_env(env_data)
            ping_results = _ping_all_providers(
                anthropic_key,
                claude_model,
                deepseek_key,
                deepseek_model,
                openrouter_key,
                saved_openrouter_prose_model or saved_openrouter_assist_model or "openrouter/auto",
                openrouter_base_url,
                openrouter_referer,
                openrouter_title,
                custom_key,
                custom_prose_model.strip() or custom_model.strip(),
                normalize_custom_base_url(custom_base_url),
            )
            st.session_state["_provider_ping_anthropic"] = ping_results["anthropic"]
            st.session_state["_provider_ping_deepseek"] = ping_results["deepseek"]
            st.session_state["_provider_ping_openrouter"] = ping_results["openrouter"]
            st.session_state["_provider_ping_custom"] = ping_results["custom"]
            saved_at = datetime.fromtimestamp(env_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            st.success(f"已保存到 .env（{saved_at}）。页面将重新载入配置。")
            st.rerun()
    
        st.divider()
    
    # ── RAG 重建 ──
    st.subheader("RAG 索引")
    st.caption("新增/修改角色档案或世界观后，重建索引以让 RAG 生效")
    rebuild_mock = st.checkbox("使用 Mock RAG 重建", value=rag_mode == "mock")
    if st.button("重建全部索引", use_container_width=True):
        with st.spinner("重建中，请稍候..."):
            try:
                apply_runtime_mode(rebuild_mock)
                from rag_engine import NovelRAG
                NovelRAG(str(PROJECT_DIR)).reindex_all()
                st.success("索引重建完成")
            except Exception as e:
                st.error(f"失败：{e}")

# ─── 共用组件：Markdown 编辑器 + 预览 ───────────────────────────────────────

def _autosave_text_widget(rel_path: str, widget_key: str, status_key: str):
    value = st.session_state.get(widget_key)
    if value is None or value == read_file(rel_path):
        return
    saved_path = write_file(rel_path, value)
    saved_at = datetime.fromtimestamp(saved_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    st.session_state[status_key] = f"已自动保存 {saved_at}"


def _autosave_json_widget(rel_path: str, widget_key: str, status_key: str):
    value = st.session_state.get(widget_key)
    if value is None or value == read_file(rel_path):
        return
    try:
        json.loads(value) if value.strip() else {}
    except json.JSONDecodeError as exc:
        st.session_state[status_key] = f"JSON 格式错误，未保存：{exc}"
        return
    saved_path = write_file(rel_path, value)
    saved_at = datetime.fromtimestamp(saved_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    st.session_state[status_key] = f"已自动保存 {saved_at}"


def _md_editor(rel_path: str, key: str, height: int = 560):
    path = PROJECT_DIR / rel_path
    content = read_file(rel_path)
    mtime_ns = path.stat().st_mtime_ns if path.exists() else 0
    editor_key = f"edit_{key}_{mtime_ns}"
    status_key = f"autosave_status_{key}"
    col_edit, col_preview = st.columns(2)
    with col_edit:
        if path.exists():
            saved_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            st.caption(f"编辑 ｜ 已落盘 {saved_at} ｜ {len(content)} 字符")
        else:
            st.caption("编辑 ｜ 文件尚未创建")
        edited = st.text_area(
            "",
            value=content,
            height=height,
            key=editor_key,
            label_visibility="collapsed",
            on_change=_autosave_text_widget,
            args=(rel_path, editor_key, status_key),
        )
    with col_preview:
        st.caption("预览")
        st.markdown(edited)
    dirty = edited != content
    save_col, reload_col = st.columns([1, 3])
    if save_col.button("保存", key=f"save_{key}", type="primary", disabled=not dirty):
        saved_path = write_file(rel_path, edited)
        st.success(f"已保存到磁盘：{saved_path.relative_to(PROJECT_DIR)}")
        st.rerun()
    if st.session_state.get(status_key):
        reload_col.success(st.session_state[status_key])
    elif dirty:
        reload_col.warning("有未保存修改。保存后页面会自动刷新并从磁盘重新载入。")
    else:
        reload_col.caption("当前内容已与磁盘一致。按 Ctrl+Enter 会自动保存编辑框内容。")


def _json_file_editor(rel_path: str, key: str, height: int = 460):
    path = PROJECT_DIR / rel_path
    raw = read_file(rel_path)
    mtime_ns = path.stat().st_mtime_ns if path.exists() else 0
    editor_key = f"json_{key}_{mtime_ns}"
    status_key = f"autosave_json_status_{key}"
    if path.exists():
        saved_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        st.caption(f"JSON 编辑 ｜ 已落盘 {saved_at} ｜ {len(raw)} 字符")
    edited = st.text_area(
        "任务卡 JSON",
        value=raw,
        height=height,
        key=editor_key,
        on_change=_autosave_json_widget,
        args=(rel_path, editor_key, status_key),
    )
    dirty = edited != raw
    col_save, col_status = st.columns([1, 2])
    try:
        parsed = json.loads(edited) if edited.strip() else {}
        valid = True
        error = ""
    except json.JSONDecodeError as exc:
        parsed = None
        valid = False
        error = str(exc)
    if col_save.button("保存任务卡 JSON", key=f"save_{key}", disabled=not dirty or not valid, type="primary"):
        saved_path = write_file(rel_path, edited)
        st.success(f"任务卡 JSON 已保存：{saved_path.relative_to(PROJECT_DIR)}")
        st.rerun()
    if st.session_state.get(status_key):
        message = st.session_state[status_key]
        if message.startswith("JSON 格式错误"):
            col_status.error(message)
        else:
            col_status.success(message)
    elif not valid:
        col_status.error(f"JSON 格式错误：{error}")
    elif dirty:
        col_status.warning("有未保存修改。保存后会从磁盘重新载入。")
    else:
        col_status.caption("当前 JSON 已与磁盘一致。按 Ctrl+Enter 会自动保存。")
    with st.expander("JSON 预览", expanded=False):
        if valid:
            st.json(parsed)
        else:
            st.code(edited, language="json")

# ─── 主函数 ─────────────────────────────────────────────────────────────────

def _nav_button(label: str, nav: str, *, page: str | None = None, chapter: int | None = None, key: str | None = None):
    if st.button(label, use_container_width=True, key=key or f"nav_btn_{nav}_{page or ''}_{chapter or ''}"):
        st.query_params["nav"] = page or nav
        if chapter is not None:
            st.query_params["chapter"] = str(chapter)
        st.rerun()


def page_writing_hub():
    render_continue_writing(PROJECT_DIR)
    st.divider()
    col_write, col_plan, col_ai = st.columns(3)
    with col_write:
        _nav_button("进入正文编辑", "写作", page="写作", key="writing_hub_open_editor")
    with col_plan:
        _nav_button("查看大纲与章纲", "规划", page="大纲", key="writing_hub_open_outline")
    with col_ai:
        _nav_button("查看 AI 草案", "AI任务", key="writing_hub_open_ai")

    tab_editor, tab_overview = st.tabs(["正文", "全书概览"])
    with tab_editor:
        page_generate()
    with tab_overview:
        page_dashboard()


def page_story_bible():
    tab_spec, tab_world, tab_style, tab_memory = st.tabs(["故事规格", "世界观与角色", "文风档案", "记忆"])
    with tab_spec:
        from project_center import CONSTITUTION, SPEC, ensure_project_center

        ensure_project_center(PROJECT_DIR)
        doc_choice = st.radio(
            "故事圣经文档",
            [SPEC, CONSTITUTION],
            horizontal=True,
            format_func=lambda rel: "故事规格" if rel == SPEC else "创作宪法",
            key="story_bible_doc_choice",
        )
        _md_editor(doc_choice, key=f"story_bible_doc_{doc_choice}", height=620)
    with tab_world:
        page_worldbuilding()
    with tab_style:
        _render_style_dossier()
    with tab_memory:
        page_memory()


def page_planning_hub():
    section = st.radio(
        "规划",
        ["启动向导", "大纲", "澄清与任务", "质量与联动", "书库"],
        horizontal=True,
        label_visibility="collapsed",
        key="planning_section",
    )
    if section == "启动向导":
        _render_startup_wizard()
        st.divider()
        _render_placeholder_help()
    elif section == "大纲":
        page_outline()
    elif section == "澄清与任务":
        from project_center import CLARIFY, TASKS, ensure_project_center, generate_clarification_questions, generate_writing_tasks

        ensure_project_center(PROJECT_DIR)
        b1, b2 = st.columns(2)
        if b1.button("生成澄清问题", use_container_width=True):
            generate_clarification_questions(PROJECT_DIR)
            st.success("澄清问题已生成")
            st.rerun()
        if b2.button("生成创作任务", use_container_width=True):
            generate_writing_tasks(PROJECT_DIR)
            st.success("创作任务已生成")
            st.rerun()
        st.divider()
        clarify_col, task_col = st.columns(2)
        with clarify_col:
            st.subheader("澄清问题")
            _md_editor(CLARIFY, key="today_project_clarify", height=420)
        with task_col:
            st.subheader("创作任务")
            _md_editor(TASKS, key="today_project_tasks", height=420)
    elif section == "质量与联动":
        from project_center import QUALITY, collect_linkage_drift_issues, ensure_project_center, generate_quality_report, write_project_status
        from prompt_assembly import build_linkage_report

        ensure_project_center(PROJECT_DIR)
        write_project_status(PROJECT_DIR)
        if st.button("生成质量报告", use_container_width=True):
            generate_quality_report(PROJECT_DIR)
            st.success("质量报告已生成")
            st.rerun()
        st.subheader("质量报告")
        st.markdown(read_file(QUALITY))
        st.divider()
        st.subheader("联动检查")
        linkage = build_linkage_report(PROJECT_DIR)
        axis = linkage.get("axis_present", {})
        cols = st.columns(len(axis) or 1)
        for col, (name, ok) in zip(cols, axis.items()):
            col.metric(name, "已接入" if ok else "待补充")
        if linkage.get("story_spec"):
            st.markdown(linkage["story_spec"])
        else:
            st.info("故事规格还没有可注入内容。补完后会自动进入世界观、总纲、角色、章纲、正文等 AI 调用。")
        linkage_issues = collect_linkage_drift_issues(PROJECT_DIR)
        if linkage_issues:
            st.warning("总纲、故事规格、卷纲或角色档案存在已声明但未同步的设定。")
            st.dataframe(linkage_issues, use_container_width=True, hide_index=True)
    else:
        page_books()


def page_ai_hub():
    tab_inbox, tab_world, tab_outline, tab_messages = st.tabs(["草案收件箱", "世界观 AI", "大纲 AI", "后台消息"])
    with tab_inbox:
        _render_ai_draft_adoption()
    with tab_world:
        st.caption("世界观与角色的生成、审查、改稿都在这里处理。")
        page_worldbuilding()
    with tab_outline:
        st.caption("总纲与章纲的生成、审查、改稿都在这里处理。")
        page_outline()
    with tab_messages:
        messages = read_inbox(PROJECT_DIR, limit=50)
        if not messages:
            st.info("暂无后台消息。")
        else:
            rows = [
                {
                    "时间": str(msg.get("created_at", "")).replace("T", " "),
                    "状态": msg.get("level", ""),
                    "标题": msg.get("title", ""),
                    "内容": msg.get("body", ""),
                    "已读": "是" if msg.get("read") else "否",
                }
                for msg in messages
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)


def page_system_settings():
    section = st.radio(
        "设置子页",
        ["设置", "日志"],
        horizontal=True,
        label_visibility="collapsed",
        key="system_settings_section",
    )
    if section == "设置":
        page_settings()
    else:
        page_logs()

def main():
    st.set_page_config(
        page_title="小说创作系统",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    active_book = activate_registered_book()
    init_session_state(st.session_state, default_mock_enabled())
    inject_app_css()

    dispatch = {
        "写作": page_writing_hub,
        "故事圣经": page_story_bible,
        "规划": page_planning_hub,
        "AI任务": page_ai_hub,
        "设置": page_system_settings,
        # V5 transition aliases.
        "今天": page_writing_hub,
        "全书": page_writing_hub,
        "笔记": page_story_bible,
        # Concrete legacy pages stay addressable for deep links and old URLs.
        "书库": page_books,
        "工作台": page_dashboard,
        "中台": page_project_center,
        "世界观": page_worldbuilding,
        "大纲": page_outline,
        "写作台": page_generate,
        "记忆": page_memory,
        "日志": page_logs,
        "设置页": page_settings,
    }

    qp = st.query_params
    nav_from_qp = qp.get("nav")
    if nav_from_qp:
        nav_from_qp = nav_from_qp[0] if isinstance(nav_from_qp, list) else nav_from_qp
    direct_page = direct_page_for(nav_from_qp)
    visible_page = visible_nav_for(nav_from_qp)
    if nav_from_qp in NAV_ITEMS:
        direct_page = None
        visible_page = nav_from_qp

    with st.sidebar:
        st.markdown("## 小说创作系统")
        st.caption("写作伴侣 V5.0-beta1")
        active_book = _render_book_sidebar(active_book)
        st.divider()
        page = st.radio(
            "nav",
            NAV_ITEMS,
            label_visibility="collapsed",
            index=NAV_ITEMS.index(visible_page) if visible_page in NAV_ITEMS else 0,
        )
        st.divider()
        _render_inbox_sidebar()
        st.caption(f"当前书籍\n{active_book.get('title', '')}")
        st.caption(f"项目路径\n{PROJECT_DIR}")
        st.divider()
        st.toggle(
            "Mock 离线模式（全局）",
            key="_global_mock",
            help="用于调试和验收，不调用外部模型。全站同步。",
        )

    if page != visible_page:
        direct_page = None
    content_page = direct_page or page

    if content_page == "写作":
        chapter_from_qp = qp.get("chapter")
        if chapter_from_qp:
            try:
                chapter_from_qp = chapter_from_qp[0] if isinstance(chapter_from_qp, list) else chapter_from_qp
                st.session_state["_query_chapter"] = int(chapter_from_qp)
            except (ValueError, TypeError):
                pass

    _render_inbox_push_channel()
    _render_lock_banner()

    dispatch[content_page]()


# 当 Streamlit 以 __main__ 运行本文件时，子模块的 `from webui import ...` 需要此注册
_main_mod = sys.modules.get("__main__")
if _main_mod is not None and getattr(_main_mod, "__file__", "").endswith("webui.py"):
    sys.modules.setdefault("webui", _main_mod)

if __name__ == "__main__":
    main()
