# AI 长篇小说创作系统

## 项目定位
本项目是本地 AI 辅助长篇小说创作中台，基于文件系统、RAG 记忆、结构化章节流程、多模型路由和 Streamlit WebUI。目标不是单次生成正文，而是让世界观、角色、总纲、章纲、章节任务卡、场景草稿、审计、定稿、滚动记忆形成可追踪闭环。

## V5.0+ 升级前必读
- 任何 V5.0 或后续版本升级、重构、诊断、WebUI 体验任务开始前，必须先阅读 `docs/V5.0_UPGRADE_PLAN.md` 和 `docs/V5.0_DESIGN_SOUL_APPENDIX.md`。
- `docs/V5.0_DESIGN_SOUL_APPENDIX.md` 是“设计灵魂与反证案例”，优先级高于普通任务拆分；实现和验收必须对照五条设计哲学、三个 wow moment 和 B 章反证案例。
- 如任务实现会误伤氛围、内省、残响、未说之语或作家裁决权，应先调整方案；不得把 score、红黄绿热力图、辅助稿文件流或阻塞式长任务当作 V5.0 的最终形态。

## 目录约定
```text
D:\cc\novel\
├── 00_世界观\
│   ├── 世界观.md
│   ├── 文风档案.md
│   └── 角色档案\
│       ├── 角色模板.md
│       └── AI草案\
├── 01_大纲\
│   ├── 总纲.md
│   ├── 卷纲\
│   │   └── 第01卷.md
│   └── 章纲\
│       ├── 第001章.md
│       ├── 第001章_task_card.json
│       └── 第001章_scenes.json
├── 02_正文\
│   ├── 第001章_草稿.md
│   ├── 第001章_修订稿.md
│   └── 第001章_定稿.md
├── 03_滚动记忆\
│   ├── 全局摘要.md
│   ├── 最近摘要.md
│   ├── 伏笔追踪.md
│   ├── 伏笔追踪.json
│   ├── 人物状态表.md
│   └── 人物状态.json
├── 04_审核日志\
├── 05_项目管理\
├── 06_项目快照\
├── 99_回收站\
├── docs\
├── prompts\
├── rag_engine.py
├── llm_router.py
├── novel_pipeline.py
├── structured_store.py
├── planning_assist.py
├── project_center.py
├── quality_diagnostics.py
├── dramatic_arc_diagnostics.py
├── literary_critic.py
├── style_court.py
├── editor_memo.py
├── voice_diagnostics.py
├── long_structure.py
├── onboarding.py
├── workflow_advisor.py
├── chapter_ops.py
├── project_archive.py
└── webui.py
```

## 核心规则
- 新角色必须先写入 `00_世界观/角色档案/`，或者先由 WebUI/CLI 生成到 `00_世界观/角色档案/AI草案/`，人工确认后再纳入正式角色档案。
- 每章进入定稿后必须更新 `03_滚动记忆/` 的四个文件，并重建 RAG 索引。
- 伏笔埋下即登记到 `03_滚动记忆/伏笔追踪.md`，收回后标记为已回收。
- 不要直接覆写 `02_正文/` 中已定稿章节；如需修改先备份。系统写入世界观、正文、记忆、项目管理文件时会自动生成 `versions/` 备份。
- 删除章节必须使用 WebUI 删除入口或 `python novel_pipeline.py --chapter N --delete-chapter --yes`，文件会移动到 `99_回收站/`，不要手工粉碎。
- `.env`、`logs/`、`.chromadb/`、`versions/`、`99_回收站/`、`06_项目快照/` 不作为代码资产提交。
- 200MB 以上文件不自动下载；给出下载页面和直链，交给用户手工下载。

## 模型与运行模式
| 任务 | 默认模型/方式 | 可选供应商 |
|------|---------------|------------|
| 正文生成（写） | `claude-opus-4-6` | Anthropic、OpenRouter 或 custom 通用接口 |
| 策划辅助（策） | `claude-opus-4-6` | Anthropic、OpenRouter、DeepSeek 或 custom 通用接口 |
| 逻辑审计（审） | `deepseek-v4-pro` | DeepSeek、OpenRouter 或 custom 通用接口 |
| 改稿（改） | `claude-opus-4-6` | Anthropic、OpenRouter、DeepSeek 或 custom 通用接口 |
| 摘要、AI 味检查、轻量索引 | `qwen3:8b` | Ollama，本地不可用时可 Mock fallback |
| RAG embedding | `D:\huggingface\bge-m3` | 真实 embedding 或 hash mock |

`.env.example` 是环境变量权威模板。重要变量：

- `NOVEL_LLM_MODE=auto|mock|real`
- `NOVEL_RAG_MODE=auto|mock`
- `NOVEL_PROSE_PROVIDER=anthropic|openrouter|custom`
- `NOVEL_ASSIST_PROVIDER=anthropic|openrouter|deepseek|custom`
- `NOVEL_REVISE_PROVIDER=anthropic|openrouter|deepseek|custom`
- `NOVEL_CRITIC_PROVIDER=deepseek|openrouter|custom`
- `NOVEL_CLAUDE_MODEL`
- `NOVEL_DEEPSEEK_MODEL`
- `OPENROUTER_API_KEY`
- `NOVEL_OPENROUTER_PROSE_MODEL`
- `NOVEL_OPENROUTER_ASSIST_MODEL`
- `NOVEL_OPENROUTER_REVISE_MODEL`
- `NOVEL_OPENROUTER_CRITIC_MODEL`
- `NOVEL_CUSTOM_API_KEY`
- `NOVEL_CUSTOM_BASE_URL`
- `NOVEL_CUSTOM_MODEL`
- `NOVEL_CUSTOM_PROSE_MODEL`
- `NOVEL_CUSTOM_ASSIST_MODEL`
- `NOVEL_CUSTOM_REVISE_MODEL`
- `NOVEL_CUSTOM_CRITIC_MODEL`
- `NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT`
- `NOVEL_CUSTOM_RETRY_MAX_TOKENS`
- `NOVEL_OLLAMA_*`
- `NOVEL_EMBED_MODEL`
- `NOVEL_COST_*_INPUT_PER_M` / `NOVEL_COST_*_INPUT_CACHE_HIT_PER_M` / `NOVEL_COST_*_INPUT_CACHE_MISS_PER_M` / `NOVEL_COST_*_OUTPUT_PER_M`：可选费用估算价格，单位为 1M tokens；Anthropic/OpenRouter 示例按 USD，DeepSeek 官方平台按 RMB/CNY。

OpenRouter 的 Anthropic 模型 ID 需要供应商前缀，例如 `anthropic/claude-opus-4-6`。WebUI 设置页在选择 OpenRouter 后，保存时会为未带 `/` 的模型自动补 `anthropic/`。`custom` 使用标准 OpenAI-compatible `/chat/completions`，`NOVEL_CUSTOM_BASE_URL` 填到 `/v1` 级别，不要包含 `/chat/completions`。设置页连接测试只验证短请求；正式写作/策划若遇到网站网关 524、timeout 或 blocked，系统会按 `NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT` / `NOVEL_CUSTOM_RETRY_MAX_TOKENS` 自动压缩重试一次。

## 常用命令
```bash
python setup_test.py
python -m unittest discover -s tests -v
python novel_pipeline.py --help

python novel_pipeline.py --reindex --mock
python novel_pipeline.py --chapter 1 --mock
python novel_pipeline.py --chapter 1 --audit-only --mock
python novel_pipeline.py --chapter 1 --quality-diagnose
python novel_pipeline.py --chapter 1 --literary-critic --mock
python novel_pipeline.py --chapter 1 --revise-from-feedback --mock
python novel_pipeline.py --chapter 1 --finalize --yes --mock

python novel_pipeline.py --chapter 1 --plan-card --mock
python novel_pipeline.py --chapter 1 --confirm-card
python novel_pipeline.py --chapter 1 --plan-scenes --mock
python novel_pipeline.py --chapter 1 --scene 1 --draft-scene --mock
python novel_pipeline.py --chapter 1 --scene 1 --review-scene --mock
python novel_pipeline.py --chapter 1 --assemble-scenes

python novel_pipeline.py --assist world --brief "核心灵感" --mock
python novel_pipeline.py --assist outline --brief "主线方向" --mock
python novel_pipeline.py --assist character --character-name "角色名" --mock
python novel_pipeline.py --assist characters --brief "批量角色要求" --mock
python novel_pipeline.py --assist chapter --chapter 1 --brief "本章目标" --mock

python novel_pipeline.py --v1-upgrade
python novel_pipeline.py --project-report
python novel_pipeline.py --init-volumes --volume-count 3
python novel_pipeline.py --chapter 1 --delete-chapter --yes --delete-reason "原因"
python novel_pipeline.py --snapshot-project --snapshot-label "milestone"
python novel_pipeline.py --list-versions
python novel_pipeline.py --restore-version "00_世界观/versions/世界观_20260101_010101.md" --yes
python novel_pipeline.py --startup-package --genre 悬疑 --brief "一句话灵感" --mock
python novel_pipeline.py --adopt-draft "00_世界观/AI草案/世界观草案_20260101_010101.md" --yes
python novel_pipeline.py --placeholder-help
streamlit run webui.py
```

## WebUI 约定
- V5.0 当前顶层导航为 `写作`、`故事圣经`、`规划`、`AI任务`、`设置`。旧入口仍通过内部路由映射保留：今天/全书/写作归入 `写作`，世界观/记忆/笔记归入 `故事圣经`，工作台/中台/大纲/书库归入 `规划`，日志/设置归入 `设置`。Mock 开关统一在侧边栏，全站同步。
- 世界观、大纲、写作、记忆等 Markdown/JSON 编辑区支持修改后 Ctrl+Enter/apply 自动保存；保留手动保存按钮。
- 设置页使用表单承载模型和运行参数，参数输入框中按 Enter 会提交并保存整组配置到 `.env`。设置页只显示当前写/策/改/审路由实际启用的供应商模型项，未启用供应商自动隐藏；常用参数按多列紧凑排布。
- 后台任务完成后写入侧边栏「站内信」和 `AI任务 / 后台消息`；前台通过轻量轮询 toast 提醒，不强制刷新正在编辑的页面。
- 世界观 AI 辅助可生成世界观草案、单角色档案草案和批量角色档案草案。
- 批量角色档案生成必须按用户指定数量落成独立角色草案；即使模型少给或标题格式松散，也要拆分/补齐为可采纳的单角色档案。
- 工作台和写作页会根据章节状态推荐下一步，优先处理占位符、每卷第一章的卷纲生成/审查/改稿、章纲审查、章纲改稿、任务卡、场景计划、草稿、审计、定稿和记忆更新；卷内后续章节不因卷纲重复阻塞。
- 日志页支持 LLM token 数和费用估算统计、全目录 `versions/` 备份检索与恢复，并可生成项目 zip 快照。恢复前会先备份当前目标文件。
- V1.4 起任务卡生成会用 LLM 识别隐式伏笔；场景计划会优先用 LLM 输出 2-6 个场景 JSON，异常时降级到保守模板；修订稿会自动复审。
- V1.5 起中台有启动向导：类型预设 + 一句话灵感可生成故事规格和 AI 草案；AI 草案可一键采纳到正式文件，采纳前会备份旧文件。
- AI 草案采纳区支持删除未采用草案；删除仅允许 `AI草案/*.md`，文件会移动到 `99_回收站/AI草案/`。
- V1.6 起定稿会用 LLM 维护结构化人物状态，写入 `人物状态表.md` 和 `人物状态.json`；伏笔表会自动升级为带来源/备注的七列格式。
- V1.7 起世界观、总纲、角色、批量角色和章纲 AI 辅助都会自动注入项目轴；WebUI `中台 / 联动检查` 可查看故事规格等上游文档是否已进入下游模块。
- V1.7.1 起策划草案必须显式写出“项目规格对齐”；Mock 辅助输出也要反映当前故事规格，不能继续使用旧通用模板。
- V1.7.2 起场景审稿、AI味/文风检查、人物状态维护、伏笔识别和场景计划也必须读取项目轴，避免后期链路只看局部文本。`audit_logic()` 内部自动注入项目轴；`review_*` 审查函数也通过 `add_project_linkage()` 注入项目轴。
- V1.8 起完整流水线会自动生成章节质量诊断；写作页智能推荐面板为主入口，高级操作收纳在「更多操作」折叠区。审核类报告（审计/AI味/读者镜像/深度检查）合并在统一的「审核报告」标签页。
- V1.9 起质量诊断会参与修订决策；低分、任务卡对齐不足、章末钩子弱或 forbidden 命中时，可用「更多操作 → 按反馈修订」进入改稿闭环。
- V2.0 起大纲页新增 `卷/幕`：`01_大纲/卷纲/第NN卷.md` 会进入项目轴、当前章节上下文、RAG、健康检查和质量报告，避免长篇阶段目标孤立。
- V2.4 起写作页按钮融合为智能推荐面板 + 折叠区、审核标签合并为统一「审核报告」、Mock 开关移至侧边栏全局控制、健康检查并入日志页、导航从 9 项精简到 8 项。
- V2.8 起增加戏剧结构诊断与风格样本注入：`dramatic_arc_diagnostics.py`（压力/弧光/画面三轴诊断），`prompts/style_seed_library.md` 内置教学样本。
- V3.0 起写作台三栏布局：章节列表/正文+操作/诊断面板三栏，戏剧雷达默认可见，改稿建议「采纳此改法」。
- V4.0 起编辑备忘录（多诊断合成）、角色声音指纹（零 API 对白区分）、技巧驱动生成（9 种硬指令技巧）、健康热力图（三色阈值+章节跳转）、场景级纯规则诊断（冲突/动作/对白）。
- V5.0-alpha2 起任务卡支持 `chapter_mode`、`ending_style`、`pacing`、`style_profile`；`style_profiles.py` 管理金庸/王小波/余华三类风格档案；作家可将误伤文学性的诊断写入 `04_审核日志/第NNN章_诊断豁免.json`，该建议不再进入扣分、清单、备忘录或改稿 prompt。
- V5.0-beta1 起写作页默认回到单栏稿纸：命令、AI 和诊断收纳为可唤出面板；质量诊断以页边批注轻量出现；全书健康图改为奶油到深褐的卷轴色带，不再使用红黄绿三色审判式热力图。
- V5.0-beta2 起新增文学批评层与风格法庭：`literary_critic.py` 生成 LiteraryView，`style_court.py` 将工程诊断分流为 confirmed/contested/literary priorities；文学风险和 contested issues 会进入 EditorMemo reservations，不进入必改项或改稿 prompt。
- V5.0-UX 收口后 inline diff 必须是块级裁决：每个差异块可单独采用或保留原文，全部裁决后才写入正文；若源文件在生成 diff 后变化，应阻止写入。主要 LLM 长任务走 `webui_infra/background_jobs.py` 后台任务条，不再把阻塞式 `st.status` 当最终体验。
- V5.0-UX 继续收口后写作页提供 `AI 自动推进当前章`：从章纲生成/采纳开始，在每卷第一章自动检查并补齐卷纲生成/审查/改稿，然后串联章纲审查、章纲改稿、任务卡、场景、草稿、审计、检查、修订和记忆更新；每步按文件状态断点续接，断点写入 `05_项目管理/AI推进断点/第NNN章.json`。不要再把用户逼到集中 AI 页来回切换。

## 文档入口
- `README.md`：快速启动和功能入口。
- `docs/ARCHITECTURE.md`：架构、数据流、核心模块。
- `docs/RUNBOOK.md`：安装、运行、环境变量、验收和故障处理。
- `docs/HANDOFF.md`：2026-05-07 阶段交接记录。

## 版本记录
| 日期 | 重点 |
|------|------|
| 2026-05-04 | 建立本地 RAG + 多模型章节流水线，支持 Mock 离线闭环。 |
| 2026-05-05 | 合并升级到 V1.0 中台：WebUI 工作台、项目管理、OpenRouter、AI 辅助规划、批量角色草案、章节删除回收、编辑自动保存、设置参数 Enter 保存。 |
| 2026-05-05 | V1.1 增加版本库与项目快照：全目录备份检索、备份恢复、恢复前保护当前文件、项目 zip 快照。 |
| 2026-05-05 | V1.4 增加结构化创作闭环：LLM 场景计划、隐式伏笔识别、修订后复审、总纲进 RAG。 |
| 2026-05-05 | V1.5 增加启动向导与草案采纳：类型预设、启动包生成、AI 草案采纳、占位符补全建议。 |
| 2026-05-05 | V1.6 增加人物状态与伏笔长期维护：结构化人物状态 JSON、定稿增量合并、伏笔七列表。 |
| 2026-05-05 | V1.7 增强模块联动：前期策划 AI 注入项目轴，中台新增联动检查。 |
| 2026-05-05 | V1.7.1 加强可见联动：策划 prompt 强制规格对齐，草案落盘补联动头，Mock 输出跟随故事规格。 |
| 2026-05-05 | V1.7.2 补强后期链路联动：场景审稿、AI味检查、人物状态、伏笔和场景计划读取项目轴。 |
| 2026-05-05 | V1.8 增加章节质量诊断：节奏/对白/套话/钩子/任务卡对齐本地检查，WebUI 和 CLI 接入。 |
| 2026-05-05 | V1.9 增加诊断驱动改稿：审计、AI味、质量诊断合成修订指令，修订后自动复审和重诊断。 |
| 2026-05-05 | V2.0 增加长篇结构层：卷/幕结构模板、当前卷上下文注入、卷纲进 RAG、WebUI 卷纲管理。 |
| 2026-05-05 | V2.2 写/审/改三角色独立路由：REVISE_PROVIDER + revise_text/revise_chapter。 |
| 2026-05-05 | V2.3 全面项目轴一致性修复：审查函数注入项目轴、audit_logic 内部自动注入项目轴、summarize_local 注入项目轴、四角色路由（新增 ASSIST_PROVIDER）、prompt 文件统一项目轴占位符、废弃一致性检查 prompt。 |
| 2026-05-05 | V2.4 前端集成优化：写作页按钮融合、审核标签合并、Mock 全局化侧边栏、健康检查并入日志。 |
| 2026-05-06 | V2.8 戏剧结构诊断与风格样本注入：dramatic_arc_diagnostics.py + style_seed_library.md。 |
| 2026-05-06 | V3.0 写作台三栏重构：webui_infra/pages/writing.py 章节列表/正文+操作/诊断面板三栏布局。 |
| 2026-05-06 | V4.0 编辑备忘录+角色声音指纹+技巧驱动生成+健康热力图+场景级诊断：editor_memo.py, voice_diagnostics.py, technique_focus, _diagnose_scene_locally。 |
| 2026-05-06 | V5.0-alpha2 章节模式、风格档案与作家豁免：ChapterMode/StyleProfile 进任务卡、prompt、诊断、EditorMemo 和改稿链路。 |
| 2026-05-06 | V5.0-beta1 单栏稿纸、页边批注、快捷键桥和卷轴健康图：webui_infra/components/* + writing.py 默认聚焦正文。 |
| 2026-05-06 | V5.0-beta2 文学批评层与风格法庭：LiteraryView、文学批评 prompt、style_court、CLI/WebUI/EditorMemo 接入，保护氛围和内省章节。 |
| 2026-05-07 | V5.0-UX 收口：删除旧测试第001章；inline diff 升级为块级采用/保留；主要 LLM WebUI 动作后台任务化；写作页 AI 自动推进支持章纲审查/改稿和断点续接；设置页按启用供应商隐藏并紧凑排布；413 项测试和 Streamlit 烟测通过。 |
