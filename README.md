# AI 长篇小说创作系统

这是一个本地文件系统版的中文长篇小说创作流水线，目标是先跑通最小闭环：

1. 读取世界观、角色档案、章纲和滚动记忆。
2. 用 RAG 组装上下文。
3. 调用真实模型或 Mock 模型生成正文。
4. 执行逻辑审计和 AI 味检查。
5. 保留草稿、修订稿、审计报告和 LLM 调用日志。
6. 人工确认定稿后更新全局摘要、最近摘要、伏笔追踪、人物状态表、结构化人物状态 JSON 和 RAG 索引。

## 快速检查

```bash
python setup_test.py
python novel_pipeline.py --help
```

## 离线跑通完整流程

不需要 API Key，不访问外部模型：

```bash
python novel_pipeline.py --reindex --mock
python novel_pipeline.py --chapter 1 --mock
python novel_pipeline.py --chapter 1 --audit-only --mock
python novel_pipeline.py --chapter 1 --quality-diagnose
python novel_pipeline.py --chapter 1 --literary-critic --mock
python novel_pipeline.py --chapter 1 --revise-from-feedback --mock
python novel_pipeline.py --chapter 1 --finalize --yes --mock
python novel_pipeline.py --init-volumes --volume-count 3
```

## 真实模型模式

复制 `.env.example` 为 `.env`，填写：

```text
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
```

然后运行：

```bash
python novel_pipeline.py --reindex
python novel_pipeline.py --chapter 1
```

如果 Ollama 没启动，摘要和 AI 味检查会自动使用本地 Mock fallback，不会中断主流程。

## 安全规则

- `.env`、`logs/`、`.chromadb/` 不进 git。
- 重复生成草稿、审计或修订稿时，旧文件会先备份到同目录 `versions/`。
- 脚本不会自动覆盖人工定稿；定稿写入和长期记忆更新必须显式使用 `--finalize --yes`。
- LLM 日志只记录输入哈希、模型、角色、状态、token 数和费用估算，不保存完整 prompt 或 API Key；DeepSeek 官方平台按人民币估算，并会使用缓存命中/未命中 token 分项计费。

## WebUI

```bash
streamlit run webui.py
```

WebUI 仍以本地文件为准；编辑世界观、大纲、正文、记忆和任务卡时会自动备份旧版本。Markdown/JSON 编辑区支持 Ctrl+Enter/apply 自动保存，设置页的参数输入框支持按 Enter 提交并保存 `.env`。

WebUI 入口：

- 顶层导航：`写作`、`故事圣经`、`规划`、`AI任务`、`设置`。
- `写作`：继续写作、单栏稿纸、AI 自动推进当前章、全书概览和卷轴健康图。
- `故事圣经`：故事规格、世界观、角色档案、文风档案和滚动记忆。
- `规划`：启动向导、大纲、卷/幕、章纲、任务卡、质量报告、联动检查和书库。
- `AI任务`：AI 草案收件箱、世界观 AI、大纲 AI 和后台消息。
- `设置`：API Key、模型路由、OpenRouter、通用 OpenAI-compatible 接口、Ollama、RAG、日志、备份、快照、健康检查和风格档案管理。
- 侧边栏提供全局 Mock 开关，所有页面同步。

## V1.0 项目中台

V1.0 把后续规划合并为项目级控制台，新增 `05_项目管理/`：

- `创作宪法.md`：不可妥协规则、质量底线和文风原则。
- `故事规格.md`：目标读者、核心冲突、卖点和成功标准。
- `澄清问题.md`：自动生成需要决策的问题。
- `创作任务.md`：从占位符、章纲、任务卡、草稿、审计和记忆状态生成任务队列。
- `质量报告.md` 和 `project_status.json`：项目级阻断项、风险项、下一步和指标快照。

命令行：

```bash
python novel_pipeline.py --v1-upgrade
python novel_pipeline.py --project-report
```

WebUI 入口：左侧导航 `中台`。推荐日常节奏：先在中台处理阻断项，再到世界观/大纲完善素材，最后进入写作页按章节闭环推进。

## 智能工作台

左侧导航 `工作台` 会自动判断当前章节的下一步：

- 章纲有占位符时，先提示具体行号。
- 任务卡缺失时，提供一键生成。
- 任务卡未确认时，引导确认。
- 场景计划缺失时，提供一键拆场景。
- 场景候选稿缺失时，自动定位第一个缺失场景。
- 场景齐备后，提示合并为章节草稿。
- 草稿、审计、AI味检查、定稿、记忆更新按顺序推进。

写作页以 AI 自动推进为主入口：系统会按章纲生成/采纳 → 每卷第一章检查卷纲，缺失时生成/审查/改稿 → 章纲审查 → 章纲改稿 → 任务卡 → 场景计划 → 场景草稿 → 审计/AI味/读者镜像/深度检查/质量诊断 → 修订 → 定稿记忆的顺序推进。每一步按当前文件状态断点续接，失败时会写入 `05_项目管理/AI推进断点/第NNN章.json`，下次点击可继续。高级手动操作仍保留为备用。

V5.0 写作页默认是单栏稿纸。AI 改稿会生成 inline diff 预览，每个差异块都可单独「采用此块」或「保留原文」；只有全部差异块裁决后才允许写入正文。主要 LLM 长任务已接入后台任务条，页面不再用全屏遮罩阻塞写作。

后台任务完成后会写入侧边栏「站内信」和 `AI任务 / 后台消息`，前台每 5 秒轻量检查未读消息并 toast 提醒，不会强制刷新正在编辑的页面。

世界观页的 `AI辅助` 支持单角色生成和批量角色生成。批量生成会根据世界观、总纲和已有角色清单生成多个角色档案草案，并自动拆分保存到 `00_世界观/角色档案/AI草案/`。

## OpenRouter

`.env.example` 已包含 OpenRouter 配置：

```text
OPENROUTER_API_KEY=
NOVEL_PROSE_PROVIDER=openrouter
NOVEL_ASSIST_PROVIDER=openrouter
NOVEL_REVISE_PROVIDER=openrouter
NOVEL_CRITIC_PROVIDER=openrouter
NOVEL_OPENROUTER_PROSE_MODEL=anthropic/claude-opus-4-6
NOVEL_OPENROUTER_ASSIST_MODEL=anthropic/claude-opus-4-6
NOVEL_OPENROUTER_REVISE_MODEL=anthropic/claude-opus-4-6
NOVEL_OPENROUTER_CRITIC_MODEL=anthropic/claude-opus-4-6
```

在 WebUI 设置页选择 OpenRouter 后，如果模型只填写 `claude-opus-4-6`，保存时会自动补成 `anthropic/claude-opus-4-6`。已经包含 `provider/model` 的 ID 不会被改写。

## 通用模型接口

设置页支持 `custom` 供应商，用于对接常见 OpenAI-compatible `/chat/completions` 接口或本地网关。填写 `NOVEL_CUSTOM_API_KEY`、`NOVEL_CUSTOM_BASE_URL` 和各角色模型后，可把写/策/改/审任一角色切到 `custom`。设置页只显示当前角色路由实际启用的供应商，未启用模型项自动隐藏；常用参数按多列紧凑排布。

```text
NOVEL_CUSTOM_API_KEY=
NOVEL_CUSTOM_BASE_URL=https://api.example.com/v1
NOVEL_CUSTOM_MODEL=
NOVEL_CUSTOM_PROSE_MODEL=your-prose-model
NOVEL_CUSTOM_ASSIST_MODEL=your-assist-model
NOVEL_CUSTOM_REVISE_MODEL=your-revise-model
NOVEL_CUSTOM_CRITIC_MODEL=your-critic-model
```

## 安全删除

WebUI 的 `规划 / 大纲 / 章纲` 和 `写作` 页面提供章节删除入口。删除前会列出相关文件和删除原因输入框；点击删除后不会直接粉碎文件，而是移动到 `99_回收站/第001章_时间戳/`。

命令行：

```bash
python novel_pipeline.py --chapter 1 --delete-chapter --yes --delete-reason "测试章节清理"
```

## V1.1 版本库与项目快照

V1.1 补齐自动备份的检索、恢复和项目级快照：

- WebUI `日志 / 文件备份` 会扫描所有 `versions/` 目录，不限正文和审核日志。
- 恢复备份前会先把当前目标文件保存为 `*_pre_restore_时间戳.*`。
- WebUI `日志 / 项目快照` 可生成 zip 快照并列出历史快照。
- 快照不包含 `.env`、`logs/`、`.chromadb/`、`versions/`、`99_回收站/` 和 `06_项目快照/`。

命令行：

```bash
python novel_pipeline.py --snapshot-project --snapshot-label "milestone"
python novel_pipeline.py --list-versions
python novel_pipeline.py --restore-version "00_世界观/versions/世界观_20260101_010101.md" --yes
```

## V1.4 结构化创作闭环

V1.4 把章节计划、伏笔和修订验证接进真实 LLM 流程：

- 生成任务卡时会让模型识别隐式伏笔，并合并到 `foreshadowing_planted/resolved`。
- `--plan-scenes` 不再固定三场景模板，会让模型根据任务卡生成 2-6 个场景 JSON；LLM 输出异常时自动降级到保守模板。
- 完整流水线中，修订稿保存后会自动生成 `04_审核日志/第NNN章_复审.md` 和对应 JSON。
- 逻辑审计参考内容包含世界观和项目轴，避免只看世界观正文。
- RAG 全量重建会索引 `01_大纲/总纲.md`。

命令行：

```bash
python novel_pipeline.py --chapter 1 --plan-card --mock
python novel_pipeline.py --chapter 1 --plan-scenes --mock
python novel_pipeline.py --chapter 1 --mock
```

## V1.5 启动向导与草案采纳

V1.5 把“新项目启动”和“AI 草案转正式文件”接成可操作链路：

- `中台 / 启动向导` 可选择类型预设，输入一句话灵感，生成故事规格并批量生成世界观、总纲、角色、第一章章纲草案。
- 支持 6 个类型预设：玄幻、都市、悬疑、言情、科幻、历史。
- `中台 / 启动向导 / AI 草案采纳` 会扫描所有 `AI草案/*.md`，自动推断正式目标文件。
- 采纳草案前会先备份已有正式文件到 `versions/`。
- 未采用的 AI 草案可在同一区域删除；删除会移动到 `99_回收站/AI草案/`，不会直接粉碎文件。
- `占位符补全建议` 会把占位符转换成可回答的问题和替换建议。

命令行：

```bash
python novel_pipeline.py --startup-package --genre 悬疑 --brief "旧案幸存者收到雨夜来信" --mock
python novel_pipeline.py --adopt-draft "00_世界观/AI草案/世界观草案_20260101_010101.md" --yes
python novel_pipeline.py --placeholder-help
```

## V1.6 人物状态与伏笔长期维护

V1.6 把定稿后的“人物状态”从待确认摘要升级为结构化连续性档案：

- 定稿时会让模型从章节正文、章纲和摘要中抽取人物位置、身体状态、情绪状态、已知信息、持有物、当前目标和关系变化。
- 自动写入 `03_滚动记忆/人物状态表.md` 与 `03_滚动记忆/人物状态.json`，后续章节会在已有状态基础上合并增量。
- 章节记忆 JSON 会同步记录本章人物状态变化，方便后续审计和 RAG 召回。
- 伏笔追踪表升级为“编号/埋入章节/伏笔内容/状态/计划回收章节/来源/备注”七列；旧五列表会自动兼容升级。
- WebUI `记忆 / 结构化记忆` 可直接查看人物状态 JSON。

验收：

```bash
python novel_pipeline.py --chapter 1 --finalize --yes --mock
```

## V1.7 模块联动增强

V1.7 重检并补强了跨模块信息流，重点避免“故事规格”等上游信息只停留在文档里：

- `prompt_assembly.build_planning_context()` 统一为世界观、总纲、角色、批量角色和章纲 AI 辅助注入项目轴。
- 项目轴包含创作宪法、故事规格摘要、文风档案和全书总纲；角色/章纲辅助还会额外带入已有世界观、角色索引和滚动记忆。
- `planning_assist.py` 的所有策划草案生成都会先拼接项目轴，再进入具体任务模板。
- 批量角色档案生成会按指定数量拆分为独立草案；模型少给时自动补齐，标题格式松散时自动规范为可采纳角色档案。
- WebUI `中台 / 联动检查` 可查看上游文档是否已接入，以及每个下游模块使用哪些信息。
- 这样“故事规格”里的目标读者、核心冲突、卖点和成功标准会自动影响世界观、总纲、角色、章纲、任务卡、场景计划和正文生成。
- V1.7.1 起策划草案开头必须出现“项目规格对齐”小节；Mock 模式也会根据当前故事规格生成对应草案，避免测试输出仍停留在旧模板。
- V1.7.2 起后期链路也统一补强：场景审稿、AI味/文风检查、人物状态维护、伏笔识别和场景计划都会读取项目轴，避免后期检查只看局部文本。`audit_logic()` 内部自动注入项目轴；策划审查函数也注入项目轴。

## V1.8 章节质量诊断

V1.8 把“能生成”继续往“能打磨”推进，新增本地章节质量诊断器：

- 完整流水线会在 AI 味检查后自动写入 `04_审核日志/第NNN章_质量诊断.md` 和 `.json`。
- 诊断不调用大模型，不额外消耗 token；它会本地统计字数、段落、句长波动、对白比例、长句/长段、套话命中、重复片段和章末钩子。
- 诊断会读取章节任务卡，检查核心事件、情绪曲线、章末钩子、伏笔可见度和 forbidden 禁止事项。
- WebUI `写作` 页新增 `章节质量诊断` 按钮和 `质量诊断` 标签页；工作台推荐也会在 AI 味检查后提示补诊断。
- 中台 `联动检查` 会显示“章节质量诊断”使用任务卡与正文稿件，避免质量报告变成孤立文件。

命令行：

```bash
python novel_pipeline.py --chapter 1 --quality-diagnose
```

## V1.9 诊断驱动改稿

V1.9 让质量诊断从“报告”进入“改稿闭环”：

- 完整流水线会先对草稿做质量诊断判断，若逻辑审计无硬伤但质量分低、章末钩子弱、任务卡对齐不足或 forbidden 命中，也会生成修订稿。
- 修订 prompt 会同时包含逻辑审计、AI 味检查和质量诊断改稿指令，避免只修逻辑、不修节奏。
- 修订稿生成后会自动复审，并重新写入最终稿对应的质量诊断报告。
- WebUI `写作` 页新增 `按反馈生成修订稿`，可对已有草稿/修订稿/定稿单独执行诊断驱动改稿。
- 工作台会在质量诊断低分或高风险时推荐 `按反馈生成修订稿`，再进入定稿草案。

命令行：

```bash
python novel_pipeline.py --chapter 1 --revise-from-feedback --mock
```

## V2.0 长篇结构层

V2.0 在章节流程之上增加“卷/幕”结构，解决长篇写到几十章后只看单章、缺少阶段约束的问题：

- 新增 `01_大纲/卷纲/第NN卷.md`，记录每卷章节范围、叙事功能、核心冲突、角色弧线、伏笔预算、节奏目标和卷末状态。
- WebUI `大纲 / 卷/幕` 可初始化、查看和编辑卷纲，编辑后同样支持 Ctrl+Enter/apply 自动保存。
- 正文生成上下文会同时带入全书卷/幕结构和当前章节所在卷纲；任务卡、场景计划、审计、修订和质量联动检查也能看到该上游约束。
- RAG 全量重建会索引卷纲，项目质量报告和健康检查会提示卷纲缺失。

命令行：

```bash
python novel_pipeline.py --init-volumes --volume-count 3
python novel_pipeline.py --reindex --mock
```

## V2.2 写/审/改三角色独立路由

V2.2 把审查和改稿从写作模型中拆出来，让三个角色走不同供应商：

- `NOVEL_PROSE_PROVIDER`：写 — 正文生成
- `NOVEL_REVISE_PROVIDER`：改 — 审后重写、策划改稿
- `NOVEL_CRITIC_PROVIDER`：审 — 逻辑审计

设置页三栏分开选择，互不影响。

## V2.3 全面项目轴一致性修复

V2.3 修复了写/审/改闭环中项目轴断裂的问题，确保所有 LLM 调用都能看到完整项目约束：

- `review_worldbuilding/review_character/review_global_outline/review_chapter_outline` 四个审查函数注入 `add_project_linkage()`，审查与改稿上下文对等。
- `audit_logic()` 内部自动调用 `build_axis_context()` 注入项目轴，调用方不再需要手动拼接。
- `summarize_local()` 注入项目轴，摘要锚定在故事规格上，避免误差沿记忆链路传递。
- 新增 `NOVEL_ASSIST_PROVIDER` 策划辅助独立路由（anthropic/openrouter/deepseek），策划和写作可使用不同模型。
- `prompts/逻辑审计.md` 和 `prompts/摘要生成.md` 统一加入项目轴占位符；`prompts/一致性检查.md` 已废弃（功能被 AI味检查和逻辑审计替代）。

## V2.4 前端集成优化

V2.4 从写作用户体验角度整合了 WebUI 的流程和按钮：

- **写作页按钮融合**：7 个独立操作按钮（完整流水线、审计、AI味、读者镜像、深度检查、质量诊断、按反馈修订）收纳到「更多操作」折叠区，智能推荐面板为主入口。保存定稿和定稿更新记忆也并入折叠区。
- **审核标签合并**：审计报告、AI味检查、读者镜像、深度检查 4 个独立标签页合并为统一的「审核报告」标签页（含 4 个子标签）。
- **Mock 全局化**：Mock 开关从 5 个页面位置移除，统一到侧边栏，全站 `_global_mock` session_state 同步。
- **导航精简**：健康检查并入日志页（新增「健康检查」子标签），侧边栏从 9 项减少到 8 项。
- 后端零改动，所有工作流和规范保持不变。

## V5.0-beta2 文学批评层与风格法庭

V5.0-beta2 把工程诊断之外的文学保护层接入流水线：

- `literary_critic.py` 生成 `04_审核日志/第NNN章_文学批评.md/json`，记录可记忆瞬间、未说之语、读者残响、文学风险和 `cannot_be_quantified`。
- `style_court.py` 生成 `04_审核日志/第NNN章_风格法庭.md/json`，把工程诊断分为 `confirmed_issues`、`contested_issues` 和 `literary_priorities`。
- `editor_memo.py` 会把文学风险和 contested issues 写入 reservations，禁止进入必改项和改稿 prompt；任务卡、forbidden、逻辑硬伤仍可 confirmed。
- WebUI 写作页诊断抽屉可查看文学批评层和风格法庭。

命令行：

```bash
python novel_pipeline.py --chapter 1 --literary-critic --mock
```

## V5.0-UX 收口：块级 diff 与后台任务

2026-05-07 对照初始 UX 设计稿完成体验收口：

- inline diff 从整稿采用/丢弃升级为差异块裁决。每个块显示当前稿和建议稿，可逐块采用或保留原文；源文件在生成建议后被改动时会阻止写入，避免覆盖新内容。
- WebUI 的主要 LLM 长任务统一走 `webui_infra/background_jobs.py`：写作 AI、单段改写、备忘录/戏剧建议改稿、智能推荐动作、主流水线、逐步审计、场景生成/审稿、世界观/大纲/启动包 AI 生成与改稿都会在后台执行。
- 写作页新增 AI 自动推进当前章，并把章纲审查与章纲改稿纳入正文生成前的自动流程；长任务失败时记录断点并尽量从已落盘草案恢复。
- 2026-05-07 已删除旧测试用第 001 章并移入回收站。后续用户可以重新创建合法的第 001 章；判断时以是否为旧测试资产为准，不以章号本身为准。

## 文档

- `docs/ARCHITECTURE.md`：模块、数据流、文件约定。
- `docs/RUNBOOK.md`：安装、运行、环境变量、验收、故障处理。
- `docs/HANDOFF.md`：2026-05-07 阶段交接记录。
