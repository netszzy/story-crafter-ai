"""
V1.5 onboarding helpers.

This module keeps onboarding file-first: presets fill the story spec, AI drafts
remain reviewable, and adoption explicitly copies a draft into a canonical file
with a backup when needed.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


GENRE_PRESETS: dict[str, dict[str, str]] = {
    "玄幻": {
        "audience": "18-35 岁，偏好升级、命运反转、清晰战力规则和强钩子的类型读者。",
        "style": "节奏偏快，动作清晰，设定名词克制投放；高光段落允许更强烈的史诗感。",
        "pace": "每章至少一个推进点，每 3-5 章一次明显反转或战力跃迁。",
        "selling": "修炼体系、血脉/传承秘密、门派或王朝压迫、阶段性爽点。",
    },
    "都市": {
        "audience": "25-40 岁，关注现实压力、人际关系、职业困境和情绪释放的读者。",
        "style": "语言贴近现实，细节具体，避免空泛鸡汤；对白承担人物关系推进。",
        "pace": "用现实事件推动冲突，章节结尾保留关系或利益变化。",
        "selling": "职场博弈、情感拉扯、阶层跃迁、旧关系重逢。",
    },
    "悬疑": {
        "audience": "喜欢线索、反转、冷读推理和不可靠叙事的读者。",
        "style": "克制、准确、重细节回收；少解释，多用行动和物证推进。",
        "pace": "每章至少投放一条线索或误导；每 5-8 章回收一个中层谜团。",
        "selling": "旧案、双线叙事、身份秘密、证据链反转。",
    },
    "言情": {
        "audience": "重视情绪张力、关系变化、人物伤口和细腻互动的读者。",
        "style": "感受具体但不直白喊情绪；用动作、停顿、误解和潜台词表现关系。",
        "pace": "每章关系状态有微变，甜/虐/误会/靠近交替推进。",
        "selling": "强关系钩子、双向救赎、身份差、久别重逢。",
    },
    "科幻": {
        "audience": "喜欢新奇设定、技术伦理、文明尺度和硬规则推演的读者。",
        "style": "概念清楚，术语少而准；用人物选择承载设定冲突。",
        "pace": "每章推进一个技术后果或伦理压力，避免纯说明书式展开。",
        "selling": "技术代价、未来社会、认知反转、文明选择。",
    },
    "历史": {
        "audience": "喜欢时代质感、权谋、人物命运和制度压力的读者。",
        "style": "语气稳重，细节有时代感但不堆考据；行动受礼法、身份、局势约束。",
        "pace": "以事件和局势变化推进，每章明确一个权力或命运转折。",
        "selling": "乱世、朝堂/家族权谋、身份抉择、历史夹缝中的个人命运。",
    },
}


@dataclass(frozen=True)
class AdoptionResult:
    source: Path
    target: Path
    backup: Path | None
    archived: Path | None = None


@dataclass(frozen=True)
class DraftDeletionResult:
    source: Path
    recycled: Path


def list_genre_presets() -> list[str]:
    return list(GENRE_PRESETS)


def build_story_spec_from_preset(
    inspiration: str,
    genre: str,
    length: str = "30-80 万字",
    pov: str = "第三人称有限视角",
    pace: str = "中快节奏",
) -> str:
    preset = GENRE_PRESETS.get(genre, GENRE_PRESETS["悬疑"])
    core = inspiration.strip() or "一个普通人被迫面对旧秘密，并在代价中完成选择。"
    return f"""# 故事规格

## 1. 一句话概括

**回答**：{core}

## 2. 目标读者

**回答**：{preset['audience']} 阅读偏好：{pace}。预计篇幅：{length}。视角：{pov}。

## 3. 核心冲突

**回答**：
- 主冲突：主角在外部压力下必须追求一个会改变命运的目标。
- 次冲突：主角的内在恐惧、旧关系或身份秘密不断干扰选择。

## 4. 主要角色

**回答**：
- 主角：待命名 · 被事件推上台前的人 · 想解决眼前危机 · 害怕真相改变自我认知
- 反派/对手：待命名 · 掌握关键资源的人 · 想维持旧秩序 · 低估主角的执念
- 挚友/同伴：待命名 · 能指出主角盲点的人 · 想保护主角 · 隐瞒一部分事实
- 导师/障碍：待命名 · 知道旧事的人 · 想让秘密停在过去 · 被自己的选择困住

## 5. 类型与卖点

**回答**：
- 类型：{genre}
- 卖点：{preset['selling']}
- 文风方向：{preset['style']}
- 节奏建议：{preset['pace']}

## 6. 成功标准

**回答**：
- 创作层面：先完成第一卷闭环，并让每章都有明确推进点。
- 读者层面：读者能清楚说出主角目标、最大阻力和最想追看的谜题。
- 质量层面：人物选择符合动机，伏笔可追踪，文风保持一致。

---

## 进阶（可选）

- 总字数预期：{length}
- 视角策略：{pov}
- 节奏策略：{pace}
"""


def write_startup_spec(
    project_dir: Path,
    inspiration: str,
    genre: str,
    length: str = "30-80 万字",
    pov: str = "第三人称有限视角",
    pace: str = "中快节奏",
) -> Path:
    from project_center import SPEC, ensure_project_center

    ensure_project_center(project_dir)
    target = project_dir / SPEC
    _backup_existing(target)
    target.write_text(
        build_story_spec_from_preset(inspiration, genre, length=length, pov=pov, pace=pace).strip() + "\n",
        encoding="utf-8",
    )
    return target


def generate_startup_package(
    project_dir: Path,
    inspiration: str,
    genre: str,
    length: str = "30-80 万字",
    pov: str = "第三人称有限视角",
    pace: str = "中快节奏",
    mock: bool = False,
) -> dict[str, object]:
    from planning_assist import (
        generate_chapter_outline_draft,
        generate_character_batch_drafts,
        generate_outline_draft,
        generate_worldbuilding_draft,
    )

    spec_path = write_startup_spec(project_dir, inspiration, genre, length=length, pov=pov, pace=pace)
    brief = (
        f"一句话灵感：{inspiration}\n"
        f"类型：{genre}\n篇幅：{length}\n视角：{pov}\n节奏：{pace}\n"
        f"类型预设：{GENRE_PRESETS.get(genre, {})}"
    )
    drafts: list[Path] = [
        generate_worldbuilding_draft(project_dir, brief, mock=mock),
        generate_outline_draft(project_dir, brief, mock=mock),
        generate_chapter_outline_draft(project_dir, 1, brief, mock=mock),
    ]
    drafts.extend(generate_character_batch_drafts(project_dir, count=3, brief=brief, mock=mock))
    return {"spec": spec_path, "drafts": drafts}


def list_ai_drafts(project_dir: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(project_dir.rglob("AI草案/*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if _is_recycled_path(project_dir, path):
            continue
        target = infer_adoption_target(project_dir, path)
        rows.append({
            "source": str(path.relative_to(project_dir)).replace("\\", "/"),
            "target": str(target.relative_to(project_dir)).replace("\\", "/"),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return rows


def infer_adoption_target(project_dir: Path, draft_path: str | Path) -> Path:
    path = _resolve_inside(project_dir, draft_path)
    rel = path.relative_to(project_dir)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if "00_世界观" in rel.parts and "角色档案" not in rel.parts:
        return project_dir / "00_世界观" / "世界观.md"
    if "角色档案" in rel.parts:
        name = _extract_character_name(text) or _clean_stem(path.stem, "角色")
        return project_dir / "00_世界观" / "角色档案" / f"{name}.md"
    if "01_大纲" in rel.parts and "卷纲" in rel.parts:
        match = re.search(r"第(\d{1,3})卷", path.name + "\n" + text)
        num = int(match.group(1)) if match else 1
        return project_dir / "01_大纲" / "卷纲" / f"第{num:02d}卷.md"
    if "01_大纲" in rel.parts and "章纲" in rel.parts:
        match = re.search(r"第(\d{1,3})章", path.name + "\n" + text)
        num = int(match.group(1)) if match else 1
        return project_dir / "01_大纲" / "章纲" / f"第{num:03d}章.md"
    if "01_大纲" in rel.parts:
        return project_dir / "01_大纲" / "总纲.md"
    return project_dir / path.name


def adopt_ai_draft(project_dir: Path, draft_rel_path: str, target_rel_path: str = "") -> AdoptionResult:
    source = _resolve_inside(project_dir, draft_rel_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"草案不存在：{draft_rel_path}")
    target = _resolve_inside(project_dir, target_rel_path) if target_rel_path else infer_adoption_target(project_dir, source)
    backup = _backup_existing(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    # 采纳后将草案移入 已采纳/ 子目录，令其从待采纳列表消失
    archive_dir = source.parent / "已采纳"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived = _unique_path(archive_dir / f"{source.stem}_{stamp}{source.suffix}")
    shutil.move(str(source), archived)
    return AdoptionResult(source=source, target=target, backup=backup, archived=archived)


def delete_ai_draft(project_dir: Path, draft_rel_path: str, reason: str = "") -> DraftDeletionResult:
    source = _resolve_ai_draft_file(project_dir, draft_rel_path)
    recycle_dir = project_dir / "99_回收站" / "AI草案"
    recycle_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    recycled = recycle_dir / f"{source.stem}_{stamp}{source.suffix}"
    recycled = _unique_path(recycled)
    shutil.move(str(source), recycled)
    if reason.strip():
        note = recycled.with_suffix(recycled.suffix + ".reason.txt")
        note.write_text(reason.strip() + "\n", encoding="utf-8")
    return DraftDeletionResult(source=source, recycled=recycled)


def placeholder_fix_suggestions(project_dir: Path) -> list[dict[str, str]]:
    from project_center import scan_placeholders

    rows = []
    for item in scan_placeholders(project_dir):
        rel = str(item["file"])
        text = str(item["text"])
        rows.append({
            "file": rel,
            "line": str(item["line"]),
            "text": text,
            "question": _question_for_placeholder(rel, text),
            "suggestion": _suggestion_for_placeholder(rel, text),
        })
    return rows


def _question_for_placeholder(rel: str, text: str) -> str:
    if "故事规格" in rel:
        return "这本书最想给谁看？主角面对的最大阻力是什么？"
    if "世界观" in rel:
        return "这个设定会怎样限制角色行动？读者需要先知道哪三条规则？"
    if "总纲" in rel:
        return "第一卷的起点、转折、高潮和代价分别是什么？"
    if "章纲" in rel:
        return "本章的视角人物、核心事件、章末钩子和禁止提前揭露的信息是什么？"
    if "角色" in rel:
        return "这个角色的目标、恐惧、弱点和说话方式分别是什么？"
    return "这里缺少哪条会影响后续生成的具体信息？"


def _suggestion_for_placeholder(rel: str, text: str) -> str:
    if "【章节标题】" in text or "章节标题" in text:
        return "用“事件 + 情绪/意象”命名，例如“雨夜来信”。"
    if "主角名" in text or "角色名" in text:
        return "先给一个临时名也可以，后续统一替换。"
    if "待补充" in text:
        return "写成一句可执行事实，不要写抽象方向。"
    return "用 1-3 句具体事实替换占位，优先写会影响剧情选择的信息。"


def _backup_existing(target: Path) -> Path | None:
    if not target.exists():
        return None
    versions = target.parent / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    backup = versions / f"{target.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{target.suffix}"
    shutil.copy2(target, backup)
    return backup


def _resolve_inside(project_dir: Path, rel_path: str | Path) -> Path:
    root = project_dir.resolve()
    path = Path(rel_path)
    full = path.resolve() if path.is_absolute() else (root / path).resolve()
    if full != root and root not in full.parents:
        raise ValueError(f"路径不在项目目录内：{rel_path}")
    return full


def _resolve_ai_draft_file(project_dir: Path, rel_path: str | Path) -> Path:
    source = _resolve_inside(project_dir, rel_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"草案不存在：{rel_path}")
    if _is_recycled_path(project_dir, source):
        raise ValueError(f"草案已在回收站中，不属于正常草案列表：{rel_path}")
    rel = source.relative_to(project_dir.resolve())
    if "AI草案" not in rel.parts or source.suffix.lower() != ".md":
        raise ValueError(f"只能删除 AI草案 目录下的 Markdown 草案：{rel_path}")
    return source


def _is_recycled_path(project_dir: Path, path: Path) -> bool:
    rel = _resolve_inside(project_dir, path).relative_to(project_dir.resolve())
    return bool(rel.parts) and rel.parts[0] == "99_回收站"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成唯一回收站文件名：{path}")


def _extract_character_name(text: str) -> str:
    patterns = [
        r"^#{1,3}\s*角色档案[：:]\s*(.+?)\s*$",
        r"^#{1,3}\s*角色档案[（(][^）)]*[）)][：:]\s*(.+?)\s*$",
        r"^\s*[-*]?\s*姓名[：:]\s*(.+?)\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            name = _safe_filename(_strip_markdown_inline(match.group(1)), "角色")
            if name not in {"项目规格对齐", "角色档案", "基础信息"}:
                return name
    return ""


def _clean_stem(stem: str, fallback: str) -> str:
    stem = re.sub(r"_?\d{8}_\d{6}$", "", stem)
    stem = re.sub(r"(草案|改稿|改进版|角色档案[（(][^）)]*[）)]：?|角色档案[：:]?)", "", stem)
    return _safe_filename(stem, fallback)


def _safe_filename(name: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\s]+', "_", name.strip()).strip("_")
    return cleaned[:40] or fallback


def _strip_markdown_inline(text: str) -> str:
    cleaned = re.sub(r"[*_`#]+", "", text or "")
    cleaned = re.sub(r"[（(].*?[）)]", "", cleaned)
    return cleaned.strip(" ：:，,。")
