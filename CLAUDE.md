# CLAUDE.md — 长篇小说写作中台

本地文件驱动的 AI 辅助长篇小说写作系统。CLI (`novel_pipeline.py`) 调度章节流水线，Streamlit WebUI (`webui.py`) 提供写作台。所有创作资产为 Markdown/JSON，无数据库。完整架构与模块清单见 `docs/ARCHITECTURE.md`。

## 快速命令

```bash
python -m unittest discover -s tests -v   # 全量测试（413 项，改完必跑）
streamlit run webui.py                     # 启动 WebUI
python novel_pipeline.py --chapter 1 --mock  # Mock 跑第 1 章完整流水线
```

## 工作约定

**改前**：跑全量测试确认基线通过。V5.0+ 涉及诊断/裁决/文学保护的改动先读 `docs/V5.0_DESIGN_SOUL_APPENDIX.md`。

**改后**：全量测试必须通过。改了公开 API 签名 → 更新 `docs/ARCHITECTURE.md`；改了环境变量 → 更新 `docs/RUNBOOK.md`。

**代码风格**：
- 新函数优先 keyword-only args，`project_dir: str | Path | None = None` 为可选项目目录参数
- Pydantic BaseModel 用于所有持久化 JSON schema（`novel_schemas.py`）
- 诊断模块之间通过各自的读写函数通信，不直接 import 内部实现细节
- WebUI 组件放 `webui_infra/components/`，页面放 `webui_infra/pages/`

**测试**：新增专项测试放 `tests/test_v5_rc1_*.py` 模式；WebUI 基础件测试放 `tests/test_webui_infra.py`。2026-05-07 当前 413 项通过；小范围 WebUI 修复至少跑 `python -m py_compile webui.py` 和 `python -m unittest tests.test_pipeline.WebUIHelperTests tests.test_webui_infra -v`。

## 红线

- `.env`、`logs/`、`.chromadb/`、`versions/`、`99_回收站/`、`06_项目快照/` 不进 commit
- 章节删除走 `chapter_ops.py`（移到 `99_回收站/`），不直接 rm
- 文学批评和风格法庭的输出是参考，不是裁决——最终决策在作家（三态按钮），代码不替人判断

## 关键路径约定

| 路径 | 约定 |
|------|------|
| `00_世界观/角色档案/AI草案/` | AI 生成的角色草案，人工确认后移入正式档案 |
| `01_大纲/章纲/第NNN章_task_card.json` | 章节任务卡，确认后才能推进结构化流程 |
| `02_正文/` | 草稿 → 修订稿 → 定稿，不直接覆写定稿 |
| `03_滚动记忆/` | 每章定稿后更新全局摘要/最近摘要/伏笔追踪/人物状态 |
| `04_审核日志/第NNN章_诊断豁免.json` | 作家裁决记录（adopt/protect/rebut），跨会话持久化 |
| `05_项目管理/style_profiles.json` | 用户自定义风格档案覆盖（与内置默认合并） |
| `versions/` | 文件覆写时自动备份，不提交 |

## V5.0 核心设计原则

1. **人机边界**：诊断给参考，裁决归人。adopt/protect/rebut 三态是作家的事，不是算法的事。
2. **不合成总分**：工程稳健度、文学密度、风格一致度三个独立指标，分别有趋势和弱章提示。
3. **文学优先**：诊断抽屉默认打开文学批评标签页，工程指标在后。
4. **本地优先**：能纯规则算的不调 LLM（质量诊断、声音指纹、场景诊断、套话检测）。
5. **写作不中断**：inline diff 做块级裁决；主要 LLM 长任务走后台任务条，不再用全屏遮罩或同步等待框阻塞写作；后台完成通过站内信和 toast 提醒，不强制刷新前台。

## 四角色 LLM 路由

| 角色 | 变量 | 可选供应商 |
|------|------|------------|
| 写 PROSE | `NOVEL_PROSE_PROVIDER` | anthropic / openrouter / custom |
| 策 ASSIST | `NOVEL_ASSIST_PROVIDER` | anthropic / openrouter / deepseek / custom |
| 改 REVISE | `NOVEL_REVISE_PROVIDER` | anthropic / openrouter / deepseek / custom |
| 审 CRITIC | `NOVEL_CRITIC_PROVIDER` | deepseek / openrouter / custom |

`NOVEL_LLM_MODE=mock` 不外调模型；`auto` 缺 Key 时降级 Mock；`real` 缺 Key 时报错。

## WebUI 当前入口

顶层导航为 `写作`、`故事圣经`、`规划`、`AI任务`、`设置`。旧深链仍兼容：今天/全书/写作到 `写作`，世界观/记忆/笔记到 `故事圣经`，工作台/中台/大纲/书库到 `规划`，日志/设置到 `设置`。

写作页的主入口是 `AI 自动推进当前章`，会按文件状态串联章纲生成/采纳、每卷第一章卷纲生成/审查/改稿、章纲审查、章纲改稿、任务卡、场景、草稿、审计、检查、修订和记忆更新；卷内后续章节不重复处理卷纲。失败时写断点到 `05_项目管理/AI推进断点/第NNN章.json`，再次点击应从当前文件状态续接。设置页只展开当前四角色路由实际启用的供应商，未用模型项自动隐藏，常用参数多列紧凑排布。

## 当前版本

V5.0 流水线清收（2026-05-10）：移除 ai_check/deep_check；改稿门控收紧为仅硬伤触发；drama_diag 保护 interior/atmosphere/bridge；reader_mirror 降为参考层；前后台16处 bug 修复。版本演进见 `docs/HANDOFF.md`。旧测试第 001 章已移入回收站；后续合法第 001 章可以存在，不要仅按章号判断为测试残留。
