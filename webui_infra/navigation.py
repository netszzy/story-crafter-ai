"""Navigation constants for the Streamlit WebUI."""

from __future__ import annotations


NAV_ITEMS = [
    "写作",
    "故事圣经",
    "规划",
    "AI任务",
    "设置",
]


NAV_ALIASES = {
    "今天": "写作",
    "📚 书库": "规划",
    "书库": "规划",
    "🏠 工作台": "规划",
    "工作台": "规划",
    "🧭 中台": "规划",
    "中台": "规划",
    "🌍 世界观": "故事圣经",
    "世界观": "故事圣经",
    "🧠 记忆": "故事圣经",
    "记忆": "故事圣经",
    "笔记": "故事圣经",
    "📋 大纲": "规划",
    "大纲": "规划",
    "全书": "写作",
    "✍️ 写作": "写作",
    "写作": "写作",
    "AI": "AI任务",
    "AI任务": "AI任务",
    "AI 草案": "AI任务",
    "📜 日志": "设置",
    "日志": "设置",
    "⚙️ 设置": "设置",
}


DIRECT_PAGE_ALIASES = {
    "📚 书库": "书库",
    "书库": "书库",
    "🏠 工作台": "工作台",
    "工作台": "工作台",
    "🧭 中台": "中台",
    "中台": "中台",
    "🌍 世界观": "世界观",
    "世界观": "世界观",
    "📋 大纲": "大纲",
    "大纲": "大纲",
    "✍️ 写作": "写作",
    "写作": "写作",
    "🧠 记忆": "记忆",
    "记忆": "记忆",
    "📜 日志": "日志",
    "日志": "日志",
    "⚙️ 设置": "设置页",
}


def visible_nav_for(label: str | None) -> str:
    """Map a legacy/deep-link label to the V5.0 top-level navigation item."""
    if not label:
        return NAV_ITEMS[0]
    return NAV_ALIASES.get(label, label if label in NAV_ITEMS else NAV_ITEMS[0])


def direct_page_for(label: str | None) -> str | None:
    """Return an old concrete page key when a deep link asks for one."""
    if not label:
        return None
    return DIRECT_PAGE_ALIASES.get(label)
