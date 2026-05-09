"""Keyboard shortcut bridge for the V5 writing surface.

Streamlit cannot receive arbitrary key events directly, so the small component
below writes a short-lived query parameter. The Python side consumes it on the
next rerun and updates session state.
"""
from __future__ import annotations

import html
from collections.abc import MutableMapping

import streamlit.components.v1 as components


SHORTCUT_ACTIONS: dict[str, str] = {
    "command": "command_palette",
    "diagnostics": "diagnostics_drawer",
    "ai": "ai_panel",
    "save": "save_paragraph",
    "focus": "focus_mode",
}


def normalize_shortcut(value: object) -> str:
    """Return a known shortcut action, accepting Streamlit query param shapes."""
    if isinstance(value, list):
        value = value[0] if value else ""
    text = str(value or "").strip().lower()
    return SHORTCUT_ACTIONS.get(text, "")


def apply_shortcut_to_state(state: MutableMapping[str, object], value: object) -> str:
    """Apply a shortcut action to a session-state-like mapping."""
    action = normalize_shortcut(value)
    if action == "command_palette":
        state["_writing_command_panel"] = True
    elif action == "diagnostics_drawer":
        state["_writing_diag_drawer"] = True
    elif action == "ai_panel":
        state["_writing_ai_panel"] = True
    elif action == "save_paragraph":
        state["_writing_save_requested"] = True
    elif action == "focus_mode":
        state["_writing_focus_mode"] = not bool(state.get("_writing_focus_mode", False))
    return action


def shortcut_cheatsheet() -> list[tuple[str, str]]:
    return [
        ("Ctrl/Cmd+P", "章节与命令"),
        ("Ctrl/Cmd+.", "诊断抽屉"),
        ("Ctrl/Cmd+K", "AI 浮窗"),
        ("Ctrl/Cmd+Enter", "保存当前稿纸"),
        ("Ctrl/Cmd+Shift+F", "专注写作"),
    ]


def render_keyboard_shortcuts(namespace: str = "writing") -> None:
    components.html(_shortcut_script(namespace), height=0, scrolling=False)


def _shortcut_script(namespace: str) -> str:
    safe_namespace = html.escape(namespace, quote=True)
    return f"""
    <script>
    (function() {{
      const namespace = "{safe_namespace}";
      if (window.parent.__novelShortcutNamespace === namespace) {{
        return;
      }}
      window.parent.__novelShortcutNamespace = namespace;
      const pushShortcut = (name) => {{
        const url = new URL(window.parent.location.href);
        url.searchParams.set("nav", "写作");
        url.searchParams.set("shortcut", name);
        window.parent.location.href = url.toString();
      }};
      window.parent.document.addEventListener("keydown", function(event) {{
        const mod = event.ctrlKey || event.metaKey;
        if (!mod) return;
        const key = (event.key || "").toLowerCase();
        if (event.shiftKey && key === "f") {{
          event.preventDefault();
          pushShortcut("focus");
        }} else if (key === "p") {{
          event.preventDefault();
          pushShortcut("command");
        }} else if (key === ".") {{
          event.preventDefault();
          pushShortcut("diagnostics");
        }} else if (key === "k") {{
          event.preventDefault();
          pushShortcut("ai");
        }} else if (key === "enter") {{
          event.preventDefault();
          pushShortcut("save");
        }}
      }}, true);
    }})();
    </script>
    """

