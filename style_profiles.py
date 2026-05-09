"""V5.0 style profiles for prose generation and local diagnostics.

Profiles are loaded from two sources, merged in order:
1. Built-in defaults (STYLE_PROFILES) — always available
2. Project-level overrides in 05_项目管理/style_profiles.json — user-configured

User profiles can add new writers or override any field of built-in defaults.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


STYLE_PROFILE_ENV = "NOVEL_STYLE_PROFILE"
USER_PROFILES_REL = "05_项目管理/style_profiles.json"


class StyleProfile(BaseModel):
    name: str
    display_name: str
    author: str = ""                           # 作家姓名
    personality_summary: str = ""              # 人格摘要：一两句话概括作家风格核心
    sample_file: str = ""                      # 样本文件路径（内置默认用）
    sample_content: str = ""                   # 样本内联内容（用户自定义优先）
    cliche_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    valued_traits: list[str] = Field(default_factory=list)
    devalued_traits: list[str] = Field(default_factory=list)
    page_turner_weight: float = 1.0
    texture_weight: float = 1.0

    def effective_sample(self, project_dir: str | Path | None = None) -> str:
        """Return sample content: user inline content first, then file content."""
        if self.sample_content.strip():
            return self.sample_content
        if self.sample_file and project_dir:
            project_dir = Path(project_dir)
            local = project_dir / self.sample_file
            bundled = Path(__file__).resolve().parent / self.sample_file
            for candidate in (local, bundled):
                if candidate.exists():
                    return candidate.read_text(encoding="utf-8")
        return ""


STYLE_PROFILES: dict[str, StyleProfile] = {
    "jin_yong": StyleProfile(
        name="jin_yong",
        display_name="金庸路线",
        author="金庸",
        personality_summary="白描动作见性格，对白藏机锋，一刀一剑皆是人物。不写心理，不铺词藻，让读者从选择里看见人。",
        sample_file="prompts/style_profiles/jin_yong.md",
        cliche_overrides={
            "深吸一口气": {"tolerable_in": ["high_tension"], "hint": "高压场景可保留，但不要连续使用。"},
        },
        valued_traits=["短句", "白描", "动作叙事", "对白潜台词"],
        devalued_traits=["长句", "意识流", "意象密集", "心理直陈"],
        page_turner_weight=1.05,
        texture_weight=0.9,
    ),
    "wang_xiaobo": StyleProfile(
        name="wang_xiaobo",
        display_name="王小波路线",
        author="王小波",
        personality_summary="机锋藏在常识里，戏谑把严肃拆成幽默。逻辑折叠处是态度，沉默里是拒绝——用聪明的话说不聪明的事。",
        sample_file="prompts/style_profiles/wang_xiaobo.md",
        cliche_overrides={
            "陷入沉默": {"allow": True, "hint": "在反讽、跳跃叙事中可作为节拍工具。"},
        },
        valued_traits=["机锋", "跳跃叙事", "戏谑", "反讽", "突然转弯"],
        devalued_traits=["工整对仗", "抒情铺陈", "宏大叙事"],
        page_turner_weight=0.7,
        texture_weight=1.08,
    ),
    "yu_hua": StyleProfile(
        name="yu_hua",
        display_name="余华路线",
        author="余华",
        personality_summary="用最平的句子写最深的痛。重复不是啰嗦是节奏，留白不是省略是尊重——让事实自己说话，不替读者感动。",
        sample_file="prompts/style_profiles/yu_hua.md",
        cliche_overrides={
            "说不出话来": {"tolerable_in": ["major_loss"], "hint": "重大变故中可作为节制留白。"},
        },
        valued_traits=["重复", "节制", "残酷的诗意", "白描血色"],
        devalued_traits=["心理直陈", "情绪解释", "修辞堆砌"],
        page_turner_weight=0.8,
        texture_weight=1.02,
    ),
}


def _resolve_profiles() -> dict[str, StyleProfile]:
    """Merge built-in defaults with project-level user overrides."""
    return STYLE_PROFILES  # caller merges at point of use via _load_user_overrides


def _load_user_overrides(project_dir: str | Path | None) -> dict[str, dict[str, Any]]:
    """Load user-configured profile overrides from project directory."""
    if project_dir is None:
        return {}
    path = Path(project_dir) / USER_PROFILES_REL
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "profiles" in data:
            return data["profiles"]
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_user_overrides(project_dir: str | Path, overrides: dict[str, dict[str, Any]]) -> Path:
    """Save user-configured profile overrides to project directory."""
    path = Path(project_dir) / USER_PROFILES_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": "5.0-rc1", "profiles": overrides}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _merge_profile(name: str, builtin: StyleProfile | None, override: dict[str, Any] | None) -> StyleProfile | None:
    """Merge a single profile: override fields on top of builtin."""
    if builtin is None and override is None:
        return None
    base = builtin.model_dump() if builtin else {}
    if override:
        base.update(override)
    base.setdefault("name", name)
    return StyleProfile(**base)


def list_style_profiles(project_dir: str | Path | None = None) -> list[StyleProfile]:
    """Return all available style profiles (builtins + user overrides merged)."""
    overrides = _load_user_overrides(project_dir) if project_dir else {}
    all_names = set(STYLE_PROFILES) | set(overrides)
    profiles = []
    for name in sorted(all_names):
        profile = get_style_profile(name, project_dir=project_dir)
        if profile is not None:
            profiles.append(profile)
    return profiles


def get_style_profile(name: str | None, *, project_dir: str | Path | None = None) -> StyleProfile | None:
    key = (name or "").strip()
    if not key:
        return None
    overrides = _load_user_overrides(project_dir) if project_dir else {}
    builtin = STYLE_PROFILES.get(key)
    override = overrides.get(key)
    if not builtin and not override:
        return None
    return _merge_profile(key, builtin, override)


def style_profile_options(project_dir: str | Path | None = None) -> dict[str, str]:
    profiles = list_style_profiles(project_dir)
    return {"": "未指定"} | {p.name: p.display_name for p in profiles}


def read_project_style_profile_name(project_dir: Path) -> str:
    env_path = Path(project_dir) / ".env"
    if not env_path.exists():
        return ""
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == STYLE_PROFILE_ENV:
                name = value.strip()
                return name if get_style_profile(name, project_dir=project_dir) is not None else ""
    except OSError:
        return ""
    return ""


def resolve_style_profile_name(project_dir: Path, chapter_num: int | None = None, card: Any | None = None) -> str:
    if card is not None:
        value = getattr(card, "style_profile", "") if not isinstance(card, dict) else card.get("style_profile", "")
        value = str(value or "").strip()
        if get_style_profile(value, project_dir=project_dir) is not None:
            return value
    if chapter_num is not None:
        path = Path(project_dir) / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_task_card.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                value = str(data.get("style_profile", "") or "").strip()
                if get_style_profile(value, project_dir=project_dir) is not None:
                    return value
            except (OSError, ValueError):
                pass
    return read_project_style_profile_name(Path(project_dir))


def merge_cliche_terms(base_terms: dict[str, dict[str, Any]], profile_name: str | None, *, project_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    merged = {term: dict(meta) for term, meta in base_terms.items()}
    profile = get_style_profile(profile_name, project_dir=project_dir)
    if profile is None:
        return merged
    for term, override in profile.cliche_overrides.items():
        current = dict(merged.get(term, {"hint": "", "tolerable_in": []}))
        current.update(override)
        merged[term] = current
    return merged


def render_style_profile_block(project_dir: Path, profile_name: str | None) -> str:
    profile = get_style_profile(profile_name, project_dir=project_dir)
    if profile is None:
        return ""
    lines = [
        "## 当前项目风格档案",
        "",
        f"- 档案：{profile.display_name}（{profile.name}）",
        f"- 作家：{profile.author}" if profile.author else "",
        f"- 人格摘要：{profile.personality_summary}" if profile.personality_summary else "",
        f"- 珍视：{'、'.join(profile.valued_traits)}",
        f"- 不强调：{'、'.join(profile.devalued_traits)}",
        f"- 追读权重：{profile.page_turner_weight:g}",
        f"- 文气权重：{profile.texture_weight:g}",
        "",
        "写作时让这些倾向自然进入句法、场面选择和信息释放；不要在正文里解释风格档案。",
    ]
    return "\n".join(line for line in lines if line)


def profile_sample_path(project_dir: Path, profile_name: str | None) -> Path | None:
    profile = get_style_profile(profile_name, project_dir=project_dir)
    if profile is None:
        return None
    local = Path(project_dir) / profile.sample_file
    if local.exists():
        return local
    bundled = Path(__file__).resolve().parent / profile.sample_file
    return bundled if bundled.exists() else None


def save_user_profile(project_dir: str | Path, profile: StyleProfile) -> Path:
    """Save a single user-configured profile (create or update)."""
    overrides = _load_user_overrides(project_dir)
    data = profile.model_dump()
    # strip fields that match builtin to keep overrides minimal
    builtin = STYLE_PROFILES.get(profile.name)
    if builtin is not None:
        builtin_data = builtin.model_dump()
        minimal = {}
        for k, v in data.items():
            if k == "name":
                minimal[k] = v
                continue
            if v != builtin_data.get(k) and v not in (None, "", [], {}):
                minimal[k] = v
        data = minimal
    overrides[profile.name] = data
    return _save_user_overrides(project_dir, overrides)


def delete_user_profile(project_dir: str | Path, profile_name: str) -> bool:
    """Delete a user-configured profile. Built-in defaults cannot be deleted."""
    if profile_name in STYLE_PROFILES:
        return False  # builtins are immutable
    overrides = _load_user_overrides(project_dir)
    if profile_name not in overrides:
        return False
    del overrides[profile_name]
    _save_user_overrides(project_dir, overrides)
    return True
