"""Session state defaults for the Streamlit WebUI.

The current app is still hosted by `webui.py`. This module centralizes stable
state keys so the later page split can reuse the same initialization path.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from copy import deepcopy
from typing import Any


SESSION_DEFAULTS: dict[str, Any] = {
    "llm_running": False,
    "writing_current_chapter": None,
    "writing_draft_dirty": False,
    "writing_draft_buffer": "",
    "writing_selected_revision_targets": [],
    "drama_diagnostics_cache": {},
    "quality_diagnostics_cache": {},
    "writing_show_sub_reports": False,
    # V5.0-beta1 写作表面
    "_writing_command_panel": False,
    "_writing_diag_drawer": False,
    "_writing_ai_panel": False,
    "_writing_focus_mode": False,
    "_writing_search_open": False,
    "_writing_save_requested": False,
    # V3.1 样本池管理
    "sample_pool_locked": {},
    "sample_pool_excluded": {},
}

DEFAULT_LLM_LOCK_MESSAGE = "大模型调用进行中，请等待完成"


def init_session_state(session_state: MutableMapping[str, Any], default_mock: bool = False) -> None:
    """Populate missing Streamlit session keys without overwriting user state."""
    session_state.setdefault("_global_mock", default_mock)
    for key, value in SESSION_DEFAULTS.items():
        session_state.setdefault(key, deepcopy(value))


def reset_chapter_buffers(session_state: MutableMapping[str, Any]) -> None:
    """Reset editor buffers after switching chapters."""
    session_state["writing_draft_dirty"] = False
    session_state["writing_draft_buffer"] = ""
    session_state["writing_selected_revision_targets"] = []


def is_llm_running(session_state: MutableMapping[str, Any]) -> bool:
    return bool(session_state.get("llm_running", False))


def set_llm_running(
    session_state: MutableMapping[str, Any],
    value: bool,
    message: str = DEFAULT_LLM_LOCK_MESSAGE,
) -> None:
    session_state["llm_running"] = value
    if value:
        session_state["llm_lock_message"] = message
    else:
        session_state.pop("llm_lock_message", None)
