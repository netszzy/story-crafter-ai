# 架构说明

更新日期：2026-05-06

## 总览
本项目是本地文件系统驱动的长篇小说写作中台。代码不依赖数据库作为主存储，所有创作资产以 Markdown 或 JSON 落在项目目录中；RAG 索引、LLM 调用日志和 WebUI 只围绕这些文件工作。

核心闭环：

1. 写入世界观、角色档案、文风档案、总纲和章纲。
2. 根据章纲生成章节任务卡，并由用户确认。
3. 根据任务卡拆分场景计划。
4. 生成场景候选稿，审稿、选择版本并合并章节草稿。
5. 生成逻辑审计、AI 味检查、章节质量诊断、文学批评层和风格法庭裁决。
6. 人工确认定稿。
7. 更新滚动记忆和 RAG 索引。

## 模块
| 模块 | 职责 |
|------|------|
| `novel_pipeline.py` | CLI 总入口，调度章节生成、审计、定稿、AI 辅助、项目中台和删除流程。 |
| `llm_router.py` | 统一 Anthropic、DeepSeek、OpenRouter、通用 OpenAI-compatible 接口、Ollama 和 Mock 调用；按工作流记录安全日志。 |
| `prompt_assembly.py` | 统一组装正文上下文、项目轴、策划上下文和联动检查报告。 |
| `rag_engine.py` | 扫描世界观、大纲、正文和滚动记忆，构建检索上下文；支持真实 embedding 和 hash mock。 |
| `structured_store.py` | 章节任务卡、LLM 场景计划、隐式伏笔识别、人物状态增量、场景审稿、候选稿选择等结构化 JSON 文件读写。 |
| `planning_assist.py` | 生成世界观、总纲、角色、批量角色和章纲草案；V1.7 起所有辅助调用都会注入项目轴。 |
| `project_center.py` | 初始化和刷新 `05_项目管理/`，生成项目状态、任务队列和质量报告。 |
| `quality_diagnostics.py` | V1.8 本地章节质量诊断：节奏、对白、句长、套话、章末钩子和任务卡对齐。 |
| `dramatic_arc_diagnostics.py` | V2.8 戏剧结构诊断：压力曲线/角色弧光/画面感三轴评估，复用 CRITIC_PROVIDER，含趋势计算。 |
| `literary_critic.py` | V5.0-beta2 文学批评层：观察可记忆瞬间、未说之语、自我欺骗、读者残响和文学风险，不输出分数。 |
| `style_court.py` | V5.0-beta2 风格法庭：把工程诊断与文学保护冲突分流为 confirmed / contested / literary priorities。 |
| `editor_memo.py` | V4.0+ 编辑备忘录合成：将诊断去重排序标矛盾；V5.0-beta2 起接入 LiteraryView 和 style_court，contested 不进必改项。 |
| `voice_diagnostics.py` | V4.0 角色声音指纹诊断：纯本地正则分析，提取对白计算句长/高频词/语气词/反问比，相似度 >70% 标记警告。 |
| `long_structure.py` | V2.0 卷/幕结构管理：初始化卷纲、解析章节范围、为项目轴和当前章节提供长篇阶段约束。 |
| `onboarding.py` | V1.5 启动向导：类型预设、故事规格生成、启动包、AI 草案采纳、占位符补全建议。 |
| `workflow_advisor.py` | 根据章节文件状态判断下一步，供 WebUI 工作台、写作页和 AI 自动推进调用；章纲完成后先推荐章纲审查与章纲改稿，再进入任务卡。 |
| `chapter_ops.py` | 安全删除章节相关文件到 `99_回收站/`。 |
| `project_archive.py` | 扫描 `versions/` 备份、恢复指定备份、生成不含秘密和索引的项目 zip 快照。 |
| `webui.py` | Streamlit WebUI，V5.0 当前顶层导航为 `写作`、`故事圣经`、`规划`、`AI任务`、`设置`；旧工作台/中台/世界观/大纲/写作/记忆/日志/设置由内部路由映射保留。写作页默认单栏稿纸，命令、AI 和诊断为唤出式面板。 |
| `webui_infra/background_jobs.py` | Streamlit 友好的后台任务状态：保存任务结果、错误、取消事件和进度，用于 WebUI 主要 LLM 长任务。任务完成后可写入站内信，由前台轻量轮询提示。 |
| `webui_infra/inbox.py` | 本地站内信通道；后台任务完成、失败或取消时写消息，侧边栏和 `AI任务 / 后台消息` 可查看。 |

## 文件数据模型
| 路径 | 数据类型 | 说明 |
|------|----------|------|
| `00_世界观/世界观.md` | Markdown | 世界设定总文档。 |
| `00_世界观/文风档案.md` | Markdown | 文风目标和样本文字。 |
| `00_世界观/角色档案/*.md` | Markdown | 正式角色档案。 |
| `00_世界观/角色档案/AI草案/*.md` | Markdown | AI 生成、待人工确认的角色草案。 |
| `01_大纲/总纲.md` | Markdown | 全书总纲。 |
| `01_大纲/卷纲/第NN卷.md` | Markdown | V2.0 卷/幕结构，记录章节范围、阶段冲突、角色弧线、伏笔预算和节奏目标。 |
| `01_大纲/章纲/第NNN章.md` | Markdown | 单章章纲。 |
| `01_大纲/章纲/第NNN章_task_card.json` | JSON | 章节任务卡，确认后才能推进结构化流程。 |
| `01_大纲/章纲/第NNN章_scenes.json` | JSON | 场景计划、候选稿、选择状态。 |
| `02_正文/第NNN章_草稿.md` | Markdown | 流水线或场景合并生成的章节草稿。 |
| `02_正文/第NNN章_修订稿.md` | Markdown | 审计后修订稿。 |
| `02_正文/第NNN章_定稿.md` | Markdown | 人工确认后的最终章节。 |
| `03_滚动记忆/*.md` | Markdown | 全局摘要、最近摘要、伏笔追踪、人物状态表。 |
| `03_滚动记忆/人物状态.json` | JSON | V1.6 结构化人物状态镜像，记录位置、身体、情绪、已知信息、持有物、目标和关系变化。 |
| `03_滚动记忆/伏笔追踪.json` | JSON | 伏笔追踪表的结构化镜像。 |
| `04_审核日志/*.md` | Markdown / JSON | 章节审计、AI 味检查、场景审稿。 |
| `04_审核日志/第NNN章_质量诊断.*` | Markdown / JSON | V1.8 章节质量诊断报告，本地生成，不消耗模型 token。 |
| `04_审核日志/第NNN章_戏剧诊断.*` | Markdown / JSON | V2.8 戏剧结构诊断报告（压力/弧光/画面），CRITIC_PROVIDER 生成。 |
| `04_审核日志/第NNN章_文学批评.*` | Markdown / JSON | V5.0-beta2 LiteraryView：可记忆瞬间、未说之语、文学风险和不可量化保护。 |
| `04_审核日志/第NNN章_风格法庭.*` | Markdown / JSON | V5.0-beta2 style_court 裁决：confirmed、contested、literary priorities。 |
| `04_审核日志/第NNN章_编辑备忘录.*` | Markdown / JSON | V4.0+ 编辑备忘录，多诊断合成去重排序；V5.0-beta2 会把文学风险写入 reservations。 |
| `04_审核日志/第NNN章_声音诊断.*` | Markdown / JSON | V4.0 角色声音指纹诊断，纯本地分析，零 API 成本。 |
| `04_审核日志/第NNN章_scene_NNN_diagnostic.json` | JSON | V4.0 场景级轻量诊断（冲突可见性/动作密度/对白推进），纯规则计算。 |
| `05_项目管理/*` | Markdown / JSON | 项目中台文档、质量报告、状态快照。 |
| `06_项目快照/*.zip` | ZIP | V1.1 项目快照，排除秘密、日志、索引、回收站和自动备份目录。 |
| `logs/llm_calls.jsonl` | JSONL | LLM 调用安全日志，只保存哈希、模型、工作流和状态。 |

## LLM 路由
`LLMRouter` 按工作流分派（V2.3 起四角色）：

| 角色 | 环境变量 | 可选供应商 |
|------|----------|------------|
| 写（PROSE） | `NOVEL_PROSE_PROVIDER` | anthropic / openrouter / custom |
| 策（ASSIST） | `NOVEL_ASSIST_PROVIDER` | anthropic / openrouter / deepseek / custom |
| 改（REVISE） | `NOVEL_REVISE_PROVIDER` | anthropic / openrouter / deepseek / custom |
| 审（CRITIC） | `NOVEL_CRITIC_PROVIDER` | deepseek / openrouter / custom |

- 摘要和 AI 味检查：Ollama，本地不可用时在 `auto` 模式下进入 Mock fallback。
- `NOVEL_LLM_MODE=mock` 时不外调模型；`auto` 时缺少依赖或 Key 会降级 Mock；`real` 时缺少依赖或 Key 会报错。

OpenRouter 使用 OpenAI SDK 兼容接口，基础 URL 默认为 `https://openrouter.ai/api/v1`。Claude 系列模型在 OpenRouter 下需要 `anthropic/` 前缀，WebUI 设置页会在保存时自动补齐。各角色 OpenRouter 模型变量：`NOVEL_OPENROUTER_PROSE_MODEL`、`NOVEL_OPENROUTER_ASSIST_MODEL`、`NOVEL_OPENROUTER_REVISE_MODEL`、`NOVEL_OPENROUTER_CRITIC_MODEL`。

通用接口使用 OpenAI-compatible `/chat/completions` 规范，适合 SiliconFlow、Moonshot、智谱、百炼、One API、LiteLLM 等网关。配置项为 `NOVEL_CUSTOM_API_KEY`、`NOVEL_CUSTOM_BASE_URL`、`NOVEL_CUSTOM_MODEL`，以及四角色模型 `NOVEL_CUSTOM_PROSE_MODEL`、`NOVEL_CUSTOM_ASSIST_MODEL`、`NOVEL_CUSTOM_REVISE_MODEL`、`NOVEL_CUSTOM_CRITIC_MODEL`。WebUI 设置页可维护这些字段并做最小 ping。

## RAG
RAG 索引源包括世界观、角色档案、总纲、卷纲、章纲、定稿和滚动记忆。真实 embedding 由 `NOVEL_EMBED_MODEL` 指定；`NOVEL_RAG_MODE=mock` 时使用确定性 hash embedding，适合离线验收。

新增或修改世界观、角色档案、章纲、定稿和滚动记忆后，应重建索引：

```bash
python novel_pipeline.py --reindex
```

## V1.4 结构化创作闭环
V1.4 后，章节计划和修订验证不再是展示层流程：

- 任务卡同步时可调用 LLM，从章纲里识别未显式写成“埋下/收回”的伏笔，并合并到任务卡。
- 场景计划优先由 LLM 根据任务卡生成 2-6 个场景 JSON，保留固定模板作为异常降级。
- 章节完整流水线在生成修订稿后会自动复审，写入 `04_审核日志/第NNN章_复审.md` 和 `第NNN章_复审.json`。
- 审计参考内容包含世界观和项目轴，避免只看局部设定。
- `reindex_all()` 会索引 `01_大纲/总纲.md` 到 `world_settings/global_outline`。

## V1.5 启动向导与草案采纳
V1.5 解决“AI 草案停在 AI草案目录、用户需要手工复制”的断层：

- `onboarding.py` 提供 6 个类型预设：玄幻、都市、悬疑、言情、科幻、历史。
- 启动包会写入 `05_项目管理/故事规格.md`，并调用 planning assist 生成世界观、总纲、批量角色和第一章章纲草案。
- 草案采纳会扫描 `AI草案/*.md`，根据目录和标题推断正式目标文件。
- 采纳前会备份已有正式文件到同目录 `versions/`。
- 占位符补全建议会把扫描结果转换成可回答的问题和替换建议。

## V1.6 人物状态与伏笔维护
V1.6 让定稿后的连续性维护更像“长篇状态数据库”：

- `CharacterState` schema 记录角色名、位置、身体状态、情绪状态、已知信息、持有物、当前目标、关系变化、来源章节和更新时间。
- `update_character_states_with_llm()` 在定稿时读取已有 `人物状态.json`，让模型抽取本章人物状态增量，再按角色名合并写回 Markdown 和 JSON。
- `write_memory_json()` 会把本章人物状态变化写入 `ChapterMemory.character_state_changes`。
- 伏笔追踪 Markdown 自动升级到七列，新增“来源”和“备注”；`parse_foreshadow_table()` 继续兼容旧五列表。
- WebUI `记忆 / 结构化记忆` 同屏展示章节记忆 JSON、伏笔 JSON 和人物状态 JSON。

## V1.7 模块联动增强
V1.7 把“项目轴”从正文生成扩展到前期策划辅助，解决故事规格、创作宪法、文风档案等上游信息对世界观/角色/大纲不起作用的问题：

- `build_planning_context(project_dir, target)` 会根据目标模块组装统一上下文。
- 世界观辅助使用：创作宪法、故事规格摘要、文风档案、全书总纲。
- 总纲辅助额外使用已有世界观。
- 角色和批量角色辅助额外使用已有世界观和角色档案索引。
- 章纲辅助额外使用已有世界观、角色档案索引和滚动记忆。
- `append_planning_context()` 会把项目轴置于具体任务输入之前，保证 LLM 先读上游约束。
- WebUI `中台 / 联动检查` 调用 `build_linkage_report()`，展示上游文档是否可用，以及每个模块的联动入口。
- V1.7.1 进一步把联动要求写进 `prompts/世界观生成.md`、`总纲生成.md`、`角色生成.md`、`角色批量生成.md` 和 `章纲生成.md`，并在草案落盘前补“项目规格对齐”可见头，方便用户肉眼确认上游规格已生效。
- V1.7.2 把同样原则扩展到后期链路：`check_ai_flavor_local()` 自动读取项目轴，`audit_logic()` 内部自动注入项目轴，`review_*` 系列函数也通过 `add_project_linkage()` 注入项目轴，场景审稿使用世界观 + 项目轴并写审稿 JSON，人物状态维护 prompt 带项目轴，伏笔识别和场景计划 prompt 明确要求服务故事规格、总纲和角色弧线。

## V1.8 章节质量诊断
V1.8 新增 `quality_diagnostics.py`，补齐 LLM 审计之外的本地可量化质量检查：

- 完整流水线和 WebUI 写作页会写入 `04_审核日志/第NNN章_质量诊断.md` 与 `.json`。
- 诊断本地计算，不调用 LLM；指标包括中文字数、段落、句子、对白比例、平均句长、句长波动、长句/长段、套话命中、重复片段和章末钩子。
- 诊断读取 `第NNN章_task_card.json`，检查核心事件、情绪曲线、章末钩子、伏笔可见度和 `forbidden` 禁止事项。
- `workflow_advisor.py` 会在 AI 味检查后推荐补质量诊断；WebUI 写作页新增独立按钮和 `质量诊断` 标签页。
- `prompt_assembly.build_linkage_report()` 已把章节质量诊断列为任务卡与正文的消费者，便于中台排查孤立信息。

## V1.9 诊断驱动改稿
V1.9 把 V1.8 的诊断报告接入改稿循环：

- `quality_diagnostics.quality_needs_revision()` 会根据评分、高风险发现、章末钩子、任务卡对齐和 forbidden 命中判断是否需要修订。
- `quality_diagnostics.render_revision_brief()` 会把质量报告压缩成改稿指令，供修订模型使用。
- `novel_pipeline.run_full()` 在逻辑审计、AI 味检查后先分析草稿质量；只要审计或质量任一侧认为需要修订，就生成 `第NNN章_修订稿.md`。
- `novel_pipeline.py --chapter N --revise-from-feedback` 可对已有稿件单独执行“审计 + AI味 + 质量诊断”合成改稿，随后自动复审和重写质量诊断。
- WebUI `写作` 页新增 `按反馈生成修订稿` 按钮；`workflow_advisor.py` 会在质量报告低分或高风险时推荐该动作。

## V2.0 长篇结构层
V2.0 把“作品 -> 章”补成“作品 -> 卷/幕 -> 章”，让长篇阶段目标进入生成链路：

- `long_structure.ensure_default_volumes()` 初始化 `01_大纲/卷纲/第NN卷.md` 模板，每卷默认覆盖 50 章。
- `prompt_assembly.build_axis_context()` 会把全书卷/幕结构放进项目轴；`build_chapter_context()` 会根据章号追加当前卷纲。
- `rag_engine.reindex_all()` 会把卷纲写入 `world_settings/volume_NN`，供后续召回。
- WebUI `大纲 / 卷/幕` 可编辑卷纲；健康检查、占位符扫描和项目质量报告会把卷纲纳入管理。
- CLI `python novel_pipeline.py --init-volumes --volume-count 3` 可补齐卷纲模板。

## WebUI 写入策略
WebUI 读写本地文件，不维护独立数据库：

- Markdown 编辑器：Ctrl+Enter/apply 自动保存，手动保存按钮保留。
- JSON 编辑器：保存前校验 JSON；格式错误时不落盘。
- 配置表单：设置页参数输入框按 Enter 提交，保存到 `.env`。
- 设置页按四角色路由动态显示供应商：只展开当前写/策/改/审实际启用的模型项，未启用供应商折叠隐藏；API Key、模型、URL、超时和本地检索参数按多列紧凑排布。
- 覆写世界观、正文、记忆和项目管理文件时，旧版本进入同目录 `versions/`。
- 章节删除移动到 `99_回收站/第NNN章_时间戳/`，并写入删除清单。
- 日志页扫描所有 `versions/` 备份，可将备份恢复到原路径；恢复前会先把当前目标文件备份为 `*_pre_restore_时间戳.*`。
- 日志页可生成项目 zip 快照；快照排除 `.env`、`logs/`、`.chromadb/`、`versions/`、`99_回收站/` 和 `06_项目快照/`。
- inline diff 预览存放在 `st.session_state["_inline_revision_preview_NNN"]`，由 `webui_infra/pages/writing.py` 拆为差异块。每个块可单独采用或保留原文，全部裁决后才调用 `write_file()` 写回；若源文件已变化则阻止写入。
- 主要 LLM 长任务通过 `_start_llm_background_job()` 进入 `webui_infra/background_jobs.py`，顶部任务条展示进度和取消请求。完成回调把结果写回 session_state 或落盘，并写入 `webui_infra/inbox.py` 管理的站内信；前台只做轻量 toast 提醒，不强制刷新正在编辑的页面。

## V2.3 策划独立路由与项目轴补强
V2.3 将前期策划辅助（世界观/总纲/角色/章纲生成）从 PROSE 拆到独立 ASSIST 角色，并补强了审计和审稿的项目轴注入：

- 新增 `NOVEL_ASSIST_PROVIDER` 和 `NOVEL_OPENROUTER_ASSIST_MODEL`，策划辅助不再占用写正文的路由。
- `audit_logic()` 内部自动注入项目轴，确保逻辑审计能看到故事规格、卷纲等上游约束。
- `review_scene()` 等 `review_*` 函数通过 `add_project_linkage()` 注入项目轴，与 V1.7.2 规划链路对齐。
- 角色档案唯一性：新角色草案保存时自动归档同角色旧草案，官方档案页检测重复文件。
- 写/策/改/审四角色独立路由：`planning_assist.py` 走 ASSIST，`revise_text/revise_chapter` 走 REVISE，`critic_text` 走 CRITIC。
- 角色档案升级为改进版：结构化规格对齐表 + 四阶段弧线 + 关系钩子。
- 世界观/大纲 AI 审查 + 改稿：审查结果暂存 session_state，改稿保存到 AI草案。

## V2.4 前端集成优化
V2.4 纯前端重构，后端零改动：

- 写作页 7 个独立按钮合并到「更多操作」折叠区，智能推荐面板为主入口。
- 审计/AI味/读者镜像/深度检查 4 个标签页合并为统一「审核报告」标签页（含子标签）。
- Mock 开关从各页面移至侧边栏，`_global_mock` session_state 全站同步。
- 健康检查并入日志页，侧边栏导航从 9 项精简到 8 项。

## V2.8 戏剧结构诊断与风格样本
V2.8 新增 `dramatic_arc_diagnostics.py` 和 `prompts/style_seed_library.md`，补齐戏剧性和文风两个维度：

- 戏剧诊断（复用 CRITIC_PROVIDER）：压力曲线（每场景 must_do/cost_if_fail/pressure_level）、角色弧光（flaw_or_desire/engaged/arc_movement）、画面感（visual/auditory/body_action/abstract_word_ratio）。
- 诊断写入 `04_审核日志/第NNN章_戏剧诊断.json` 和 `.md`，WebUI 写作页右栏雷达默认可见。
- `DramaTrends` 跨章滚动均值与趋势方向（improving/declining/stable），WebUI 仪表板可视化。
- 风格样本池：`prompts/style_seed_library.md` 内置 8 段教学样本，`inject_prose_samples` 从用户标尺/样本池/种子库/已定稿章节选 3 段注入正文生成 prompt。

## V3.0 写作台三栏重构
V3.0 将写作页从单栏重构为三栏布局，`webui_infra/` 模块包正式成立：

- 三栏：章节列表 (1) ｜ 正文+主操作 (3) ｜ 诊断面板 (2)。
- 主操作 3 按钮（流水线/改稿/定稿）始终可见，根据诊断分数自动高亮推荐动作。
- 戏剧诊断雷达默认可见，`top_revision_targets` 每条带「采纳此改法」按钮。
- `webui_infra/state.py` 管理 session_state，`webui_infra/navigation.py` 管理导航常量。

## V4.0 写作质量与操作体验升级
V4.0 分四 Phase 实施，补齐诊断碎片化、前台操作按钮驱动、角色声音区分和场景级把关：

### Phase A：编辑备忘录
- `editor_memo.py`：将所有诊断（审计/AI味/读者镜像/深度检查/质量/戏剧）合成为 ≤500 字编辑备忘录。
- `EditorMemo` 模型含 `top_3_must_fix`（优先级+来源+改法+验收标准）、`contradictions`（诊断间矛盾标记）、`score_summary`、`ready_to_finalize`。
- 改稿 prompt 从 ~7000 token（7 块扁平拼接）压缩到 ~1200 token（仅备忘录）。
- WebUI 写作页右栏一级展示备忘录（top-3 + 采纳按钮），二级折叠雷达，三级折叠子报告。

### Phase B：角色声音指纹 + 修订 diff
- `voice_diagnostics.py`：纯本地正则分析（零 API 成本），提取每角色对白，计算句长/高频词 (2-gram)/语气词频率/反问比例。
- 余弦相似度 > 70% 标记警告，注入 prose 生成和 revise prompt。
- `difflib.unified_diff` 对比草稿 vs 修订稿，统计新增/删除行数。

### Phase C：技巧驱动生成 + 正文编辑区
- `ChapterTaskCard.technique_focus`：任务卡新增技巧焦点字段，9 种中文写作技巧可选。
- `render_technique_enforcement()`：将选中技巧转为硬指令注入 prose 生成 prompt。
- `scene_type_techniques()`：根据场景类型（开场/对峙/情感/动作/揭示/过渡/高潮/尾声）自动推荐技巧。
- 正文 tab 从 `st.markdown` 改为 `st.text_area`（600px），支持直接编辑 + 保存。
- AI 辅助润色：起止行号 + 6 种动作（描写代替叙述/对白精炼/感官细节/身体化情绪/强化钩子/句式多样化）+ 单段改写。

### Phase D：健康热力图 + 场景级诊断
- `_render_chapter_health_heatmap()`：仪表板戏剧趋势下方渲染彩色方块（绿 ≥80/黄 ≥60/红 <60），双维度（戏剧+质量），点击跳转写作页。
- `_diagnose_scene_locally()`：纯规则场景诊断（冲突可见性/身体动作密度/对白推进），零 API 成本。
- `SceneDiagnosticNote` 模型，`ScenePlan` 新增 `diagnostic_score`/`diagnostic_notes` 字段。
- `run_scene_review()` 末尾自动触发场景诊断，回写 ScenePlan。

## V5.0-alpha2 章节模式、风格档案与作家豁免
V5.0-alpha2 将附录中的”避免误伤文学性”落成结构化入口：

- `ChapterTaskCard` 新增 `chapter_mode`、`ending_style`、`pacing`、`style_profile`。旧任务卡缺字段时默认兼容为 `plot/hook/normal`。
- `style_profiles.py` 管理风格档案：三个内置默认（`jin_yong`/`wang_xiaobo`/`yu_hua`），每个档案有原作者选段样本、人格摘要、套话覆盖、珍视/不强调特征和追读/文气权重。支持用户在 WebUI 设置页新增/编辑/删除自定义档案，存档到 `05_项目管理/style_profiles.json`，与内置默认合并生效。
- `prompt_assembly.render_prose_system_prompt()` 会按任务卡或 `.env` 的 `NOVEL_STYLE_PROFILE` 注入风格档案、章节模式规则和 profile 样本。
- `quality_diagnostics.py` 按 ChapterMode 查阈值：`interior/atmosphere` 的 conflict 下限为 0，open/echo 结尾允许余味，不强制硬钩子。
- `04_审核日志/第NNN章_诊断豁免.json` 记录作家裁决；`apply_writer_overrides()` 将对应 finding 按 action（adopt/protect/rebut）三态处理。adopt 不退分且保持活跃；protect/rebut 退分并标记为 `accepted_by_writer`/`rebutted_by_writer`，不再进入扣分、改稿清单和 revision brief。
- `EditorMemo` 新增 `reservations`、`style_profile`、`chapter_mode`，改稿 prompt 明确禁止执行作家已拒绝的建议。

## V5.0-rc1 作家裁决面板、文学批评独立面板与三维项目健康
V5.0-rc1 将裁决权还给作家，拆开诊断展示，并把项目健康从单分数改为三个独立维度：

- **三态裁决**：每条诊断 finding 支持 adopt（采纳）/ protect（保护）/ rebut（反驳）三种作家裁决，统一覆盖质量诊断、风格法庭 contested、文学风险和编辑备忘录。裁决持久化到 `04_审核日志/第NNN章_诊断豁免.json`。
- **文学批评独立面板**：诊断抽屉改为标签页结构（文学批评/工程诊断/风格法庭/备忘录），默认激活文学批评。完整展示可记忆瞬间、未说之语、道德灰度、自我欺骗、读者残响和文学风险。
- **三维项目健康**：`ProjectHealthSnapshot` 以工程稳健度、文学密度、风格一致度三个独立指标替代单一总分。`ScrollHealthChapter` 支持三维独立分数。仪表板显示三指标卡片和趋势箭头。
- **风格档案 WebUI 管理**：设置页新增”风格档案管理”区块，可查看/新增/编辑/删除风格档案，配置持久化到 `05_项目管理/style_profiles.json`。
- rc1 当时全量 410 项单元测试通过；2026-05-07 V5.0-UX 收口后全量 413 项通过。

## V5.0-beta1 单栏稿纸与卷轴健康图
V5.0-beta1 将 V4.0 的三栏驾驶舱收束成写作优先界面：

- `webui_infra/pages/writing.py` 默认渲染单栏稿纸，顶部只保留章节切换、章节标题、诊断、AI、搜索和更多；章节命令、AI 辅助和诊断抽屉由按钮或快捷键唤出。
- `webui_infra/components/margin_notes.py` 将质量诊断和精修片段整理成最多 5 条页边批注，支持“看看”和“不用”；“不用”会写入 `04_审核日志/第NNN章_诊断豁免.json`。
- `webui_infra/components/keyboard.py` 用轻量 Streamlit component 捕获 `Ctrl/Cmd+P`、`Ctrl/Cmd+.`、`Ctrl/Cmd+K`、`Ctrl/Cmd+Enter` 和 `Ctrl/Cmd+Shift+F`，再通过 query param 更新 session state。
- `webui_infra/components/scroll_health.py` 替换旧健康热力图：每章是横向 8px 色带，颜色从奶油到深褐连续映射，弱章以“第 N 章在等你”提示，浮卡数据包含一句总结、最严重诊断和可保留原文。

## V5.0-beta2 文学批评层与风格法庭
V5.0-beta2 把附录 B.1/B.2 的“避免误伤文学性”落成一条并行诊断链：

- `LiteraryView` / `MemorableMoment` 写入 `novel_schemas.py`，字段覆盖可记忆瞬间、未说之语、道德灰度、自我欺骗、读者残响、文学风险和 `cannot_be_quantified`。
- `literary_critic.py` 使用 `prompts/文学批评.md` 和 CRITIC_PROVIDER 生成主观文学观察；Mock 模式只做启发式占位，并明确写出未做真实文学评估。
- `style_court.py` 读取质量诊断、任务卡口径和 LiteraryView，把硬约束留在 `confirmed_issues`，把会误伤克制/氛围/未说之语的建议放入 `contested_issues`。
- `editor_memo.py` 接收 `literary_view` 和 `style_court_decision`；文学风险和 contested issues 自动进入 `reservations`，禁止进入 `top_3_must_fix` 或改稿 prompt。
- CLI 新增 `python novel_pipeline.py --chapter N --literary-critic --mock`，完整流水线和按反馈修订也会生成文学批评与风格法庭文件。
- WebUI 写作页诊断抽屉新增“文学批评层”和“风格法庭”折叠区，和工程指标分开展示。

## V5.0-UX 收口：块级 diff、后台任务与自动推进
2026-05-07 对照初始 UX 设计稿完成体验收口：

- `webui_infra/pages/writing.py` 将 inline revision 从整稿 unified diff 升级为 `difflib.SequenceMatcher` 差异块。每个非 equal 块显示当前稿/建议稿，并提供“采用此块 / 保留原文”；`_compose_inline_revision()` 只合成已裁决版本，防止模型建议绕过作家裁决。
- `webui.py` 提供 `_start_llm_background_job()` 包装 `start_background_job()`；写作 AI、单段润色、备忘录/戏剧建议改稿、智能推荐动作、主流水线、逐步审计、场景生成/审稿/对比、世界观/大纲/启动包 AI 生成与改稿均使用后台任务。
- `webui_infra/background_jobs.py` 的 `BackgroundJob` 保存 `result`、`error`、`on_success` 和 `on_error`，让 Streamlit 下一次 rerun 时回填结果或展示错误。
- `webui_infra/pages/writing.py` 的 AI 自动推进按 `workflow_advisor.chapter_flow()` 的推荐循环执行：章纲生成/采纳、每卷第一章卷纲生成/审查/改稿、章纲审查、章纲改稿、任务卡、场景计划、场景草稿、章节草稿、审计、AI味、读者镜像、深度检查、质量诊断、反馈修订、定稿记忆。卷内后续章节不重复处理卷纲；每一步完成后重新读取文件状态；失败时写 `05_项目管理/AI推进断点/第NNN章.json`，并在下一次点击时按当前文件状态续接。
- 章节删除验收后，旧测试用第 001 章已移入 `99_回收站/第001章_20260507_013144/`。后续用户可以重新创建合法第 001 章；维护时不要仅凭 `第001章*` 文件名判断为测试残留。
