# 运行手册

更新日期：2026-05-06

## 环境准备
推荐 Python 3.11。进入项目目录：

```bash
cd D:\cc\novel
```

基础检查：

```bash
python setup_test.py
python novel_pipeline.py --help
python -m unittest discover -s tests -v
```

启动 WebUI：

```bash
streamlit run webui.py
```

## 环境变量
复制 `.env.example` 为 `.env`，按需填写：

```text
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
OPENROUTER_API_KEY=
NOVEL_CUSTOM_API_KEY=

NOVEL_PROSE_PROVIDER=anthropic
NOVEL_REVISE_PROVIDER=deepseek
NOVEL_ASSIST_PROVIDER=anthropic
NOVEL_CRITIC_PROVIDER=deepseek
NOVEL_LLM_MODE=auto
NOVEL_RAG_MODE=auto
NOVEL_EMBED_MODEL=D:\huggingface\bge-m3
```

模式说明：

- `NOVEL_LLM_MODE=mock`：不调用外部模型，适合离线验收。
- `NOVEL_LLM_MODE=auto`：有 Key 和依赖时真实调用，缺失时 fallback 到 Mock。
- `NOVEL_LLM_MODE=real`：强制真实调用，缺少 Key 或依赖时报错。
- `NOVEL_RAG_MODE=mock`：使用 hash embedding。
- `NOVEL_RAG_MODE=auto`：优先真实 embedding，失败时 fallback。

OpenRouter 示例：

```text
NOVEL_PROSE_PROVIDER=openrouter
NOVEL_REVISE_PROVIDER=openrouter
NOVEL_ASSIST_PROVIDER=openrouter
NOVEL_CRITIC_PROVIDER=openrouter
OPENROUTER_API_KEY=
NOVEL_OPENROUTER_PROSE_MODEL=anthropic/claude-opus-4-6
NOVEL_OPENROUTER_REVISE_MODEL=anthropic/claude-opus-4-6
NOVEL_OPENROUTER_ASSIST_MODEL=anthropic/claude-opus-4-6
NOVEL_OPENROUTER_CRITIC_MODEL=anthropic/claude-opus-4-6
```

通用 OpenAI-compatible 接口示例：

```text
NOVEL_PROSE_PROVIDER=custom
NOVEL_REVISE_PROVIDER=custom
NOVEL_ASSIST_PROVIDER=custom
NOVEL_CRITIC_PROVIDER=custom
NOVEL_CUSTOM_API_KEY=
NOVEL_CUSTOM_BASE_URL=https://api.example.com/v1
NOVEL_CUSTOM_MODEL=
NOVEL_CUSTOM_PROSE_MODEL=your-prose-model
NOVEL_CUSTOM_REVISE_MODEL=your-revise-model
NOVEL_CUSTOM_ASSIST_MODEL=your-assist-model
NOVEL_CUSTOM_CRITIC_MODEL=your-critic-model
NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT=24000
NOVEL_CUSTOM_RETRY_MAX_TOKENS=6000
```

`NOVEL_CUSTOM_BASE_URL` 填到 `/v1` 级别，不要包含 `/chat/completions`。该通用接口适配提供 OpenAI-compatible chat completions 的云供应商或 One API、LiteLLM 等本地网关。
设置页的连通测试只发送极短请求，用于验证地址、模型 ID 和 API Key；正式写作/策划会发送长上下文。若通用网站网关返回 524、timeout 或 `Your request was blocked`，系统会自动用 `NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT` 和 `NOVEL_CUSTOM_RETRY_MAX_TOKENS` 压缩重试一次；仍失败时应优先把“写/策”切到 Anthropic、OpenRouter 或 DeepSeek，或换支持长任务/流式转发的网关。

## CLI 流程
离线完整验收：

```bash
python novel_pipeline.py --reindex --mock
python novel_pipeline.py --chapter 1 --mock
python novel_pipeline.py --chapter 1 --audit-only --mock
python novel_pipeline.py --chapter 1 --quality-diagnose
python novel_pipeline.py --chapter 1 --revise-from-feedback --mock
python novel_pipeline.py --chapter 1 --finalize --yes --mock
python novel_pipeline.py --init-volumes --volume-count 3
```

结构化章节流程：

```bash
python novel_pipeline.py --chapter 1 --plan-card --mock
python novel_pipeline.py --chapter 1 --confirm-card
python novel_pipeline.py --chapter 1 --plan-scenes --mock
python novel_pipeline.py --chapter 1 --scene 1 --draft-scene --mock
python novel_pipeline.py --chapter 1 --scene 1 --review-scene --mock
python novel_pipeline.py --chapter 1 --scene 1 --compare-scene
python novel_pipeline.py --chapter 1 --scene 1 --select-draft 1
python novel_pipeline.py --chapter 1 --assemble-scenes
```

V1.4 说明：

- `--plan-card` 会在 Mock/真实模式下尝试识别隐式伏笔并写入任务卡。
- `--plan-scenes` 会优先调用 LLM 生成场景 JSON；LLM 输出异常时降级到保守模板。
- `python novel_pipeline.py --chapter 1 --mock` 如果生成修订稿，会额外写入复审报告。

前期策划辅助：

```bash
python novel_pipeline.py --assist world --brief "核心灵感" --mock
python novel_pipeline.py --assist outline --brief "主线方向" --mock
python novel_pipeline.py --assist character --character-name "角色名" --mock
python novel_pipeline.py --assist characters --brief "批量角色要求" --mock
python novel_pipeline.py --assist chapter --chapter 1 --brief "本章目标" --mock
```

项目中台：

```bash
python novel_pipeline.py --v1-upgrade
python novel_pipeline.py --project-report
```

安全删除：

```bash
python novel_pipeline.py --chapter 1 --delete-chapter --yes --delete-reason "原因"
```

版本库与项目快照：

```bash
python novel_pipeline.py --snapshot-project --snapshot-label "milestone"
python novel_pipeline.py --list-versions
python novel_pipeline.py --restore-version "00_世界观/versions/世界观_20260101_010101.md" --yes
```

启动向导与草案采纳：

```bash
python novel_pipeline.py --startup-package --genre 悬疑 --brief "旧案幸存者收到雨夜来信" --mock
python novel_pipeline.py --adopt-draft "00_世界观/AI草案/世界观草案_20260101_010101.md" --yes
python novel_pipeline.py --placeholder-help
```

V1.6 人物状态与伏笔维护：

- `--finalize --yes` 会同步更新 `人物状态表.md`、`人物状态.json`、`伏笔追踪.md`、`伏笔追踪.json` 和章节记忆 JSON。
- 旧版五列伏笔表会在下一次定稿更新时自动升级为七列。
- 如果人物状态抽取失败，会保留旧的待确认摘要降级路径，不中断定稿。

V1.7 模块联动检查：

- 在 WebUI `中台 / 联动检查` 查看故事规格、创作宪法、文风档案、总纲是否已接入。
- 世界观、总纲、角色、批量角色和章纲 AI 辅助会自动携带项目轴，不需要用户手工复制故事规格。
- 如果联动检查显示”待补上游”，先补对应文档，再生成 AI 草案。
- 生成后的 AI 草案应在开头出现”项目规格对齐”；如果没有，说明走到了旧代码或旧进程，重启 WebUI 后重试。
- 场景审稿、AI味检查、人物状态维护也应显示/记录对项目轴的参考；若检查结果完全像通用模板，先重启 WebUI，再确认 `中台 / 联动检查` 中上游文档不为空。
- `audit_logic()` 内部自动注入项目轴，逻辑审计不再需要手工拼上游设定。

V1.8 章节质量诊断：

- 完整流水线会自动生成 `04_审核日志/第NNN章_质量诊断.md` 和 `.json`。
- 单独诊断当前稿件可运行：

```bash
python novel_pipeline.py --chapter 1 --quality-diagnose
```

- 质量诊断不调用大模型，不消耗 token；它会检查节奏、对白比例、句长、套话、重复片段、章末钩子和任务卡对齐。
- 如果诊断报告提示 forbidden 命中，优先修正文稿或任务卡，因为这代表正文触碰了本章明确禁止事项。

V1.9 诊断驱动改稿：

- 完整流水线会把质量诊断纳入修订判断，不再只依赖逻辑审计。
- 单独根据已有审计、AI味和质量诊断生成修订稿：

```bash
python novel_pipeline.py --chapter 1 --revise-from-feedback --mock
```

- 该命令会写入 `02_正文/第NNN章_修订稿.md`，并自动生成 `04_审核日志/第NNN章_复审.md/json` 与最新 `第NNN章_质量诊断.md/json`。
- WebUI `写作` 页可点击 `按反馈生成修订稿`；V5.0-UX 收口后主要 LLM 操作进入后台任务条，页面不会被全屏遮罩阻塞，但同一时间仍只允许一个模型任务，避免重复点击浪费调用。

V2.0 长篇结构层：

- 初始化卷/幕结构模板：

```bash
python novel_pipeline.py --init-volumes --volume-count 3
```

- 卷纲位于 `01_大纲/卷纲/第NN卷.md`，每份包含章节范围、叙事功能、核心冲突、角色弧线、伏笔预算、节奏目标和卷末状态。
- 正文生成会把全书卷/幕结构放入项目轴，并根据当前章号追加当前卷纲。
- 修改卷纲后建议重建索引：

```bash
python novel_pipeline.py --reindex --mock
```

## WebUI 验收
1. 打开 `http://localhost:8501`。
2. 顶层导航应为 `写作`、`故事圣经`、`规划`、`AI任务`、`设置`；旧入口通过内部路由映射到这些区域。
3. 进入 `设置 / 日志 / 健康检查`，确认目录、环境变量、Schema、任务卡检查能正常显示。
4. 进入 `设置`，确认只展开当前写/策/改/审路由实际启用的供应商；修改一个非敏感参数，按 Enter，确认 `.env` 更新时间变化。
5. 进入 `故事圣经 / 世界观与角色`，修改 Markdown 后 Ctrl+Enter/apply，刷新页面确认内容仍存在。
6. 进入 `故事圣经 / 世界观与角色 / AI辅助`，使用 Mock 模式生成世界观、单角色或批量角色草案；页面应显示后台任务条，不出现全屏遮罩。
7. 进入 `规划 / 大纲 / 卷/幕`，初始化并编辑卷纲，确认刷新后内容仍存在。
8. 进入 `规划 / 大纲`，生成或编辑章纲；写作页自动推进会在每卷第一章、任务卡前补卷纲生成/审查/改稿，卷内后续章节只补章纲审查和章纲改稿。
9. 进入 `写作`，点击 `AI 自动推进当前章`，确认它按当前文件状态继续下一步；展开手动操作可执行分步操作（审计、AI味、读者镜像、深度检查、质量诊断、按反馈修订）。
10. 在写作页生成 inline diff，确认每个差异块都有「采用此块 / 保留原文」，全部裁决后才能写入。
11. 使用章节删除入口时，确认会列出相关文件并填写删除原因；删除结果应进入 `99_回收站/`。
12. 打开写作页诊断抽屉，确认文学批评、工程诊断、风格法庭、备忘录四个标签页都能正常展示。
11. 进入 `写作`，展开「更多操作 → 按反馈修订」，确认修订稿、复审和新质量诊断正常生成。
12. 进入 `日志 / 文件备份`，确认能看到所有 `versions/` 备份；恢复备份需输入 `RESTORE`。
13. 进入 `日志 / Token费用`，确认能看到调用次数、输入/输出 token、总 token 和费用估算；DeepSeek 官方平台应以人民币显示，且缓存命中/未命中 token 会分列。
14. 进入 `日志 / 项目快照`，生成快照后确认 `06_项目快照/` 下出现 zip 文件。
15. 进入 `中台 / 启动向导`，用 Mock 模式生成启动包，确认故事规格写入、AI 草案生成。
16. 在 `AI 草案采纳` 中确认系统推断的目标文件，点击采纳，确认正式文件被写入且旧文件进入 `versions/`。
17. 进入 `记忆 / 结构化记忆`，确认章节记忆 JSON、伏笔 JSON、人物状态 JSON 都能展示。
18. 进入 `中台 / 联动检查`，确认故事规格、卷/幕结构等上游文档已进入世界观、总纲、角色、章纲和正文生成链路。

## 故障处理
| 现象 | 处理 |
|------|------|
| OpenRouter 调 Claude 失败 | 确认模型 ID 是否为 `anthropic/claude-opus-4-6` 形式，确认 `OPENROUTER_API_KEY` 已设置。 |
| 通用接口连接测试成功但正式调用失败 | 连接测试只发短请求；正式写作可能触发网站网关 524 超时或 WAF 拦截。查看 `logs/llm_calls.jsonl` 的 `error`。系统会自动压缩重试一次；仍失败时调低 `NOVEL_CUSTOM_RETRY_INPUT_CHAR_LIMIT` / `NOVEL_CUSTOM_RETRY_MAX_TOKENS`，或把“写/策”切到更稳定的供应商。 |
| 日志里显示 `mock-assist` | 说明当次 AI 辅助走的是离线 Mock。确认侧边栏 `Mock 离线模式` 已关闭，并在日志/健康检查中确认 Anthropic SDK / OpenAI SDK 可导入。 |
| Anthropic 提示 Streaming is required | 长输出请求会自动切到流式；若仍出现，确认已重启 WebUI，并检查 `NOVEL_ANTHROPIC_STREAM_THRESHOLD_TOKENS` 不要设得过高。 |
| DeepSeek 或 Anthropic Key 缺失 | 使用 `NOVEL_LLM_MODE=mock` 跑离线流程，或补齐 `.env`。 |
| Ollama 不可用 | `auto` 模式下会 fallback；需要真实本地摘要时启动 Ollama 并安装 `qwen3:8b`。 |
| RAG embedding 下载失败 | 设置 `NOVEL_RAG_MODE=mock` 或检查 `NOVEL_EMBED_MODEL` 路径。 |
| WebUI 刷新后内容丢失 | 确认编辑区使用 Ctrl+Enter/apply 或保存按钮；2026-05-05 后 Markdown/JSON 编辑区已自动保存。 |
| JSON 任务卡无法保存 | 修正 JSON 格式错误后再保存。 |
| 删除章节后想恢复 | 从 `99_回收站/第NNN章_时间戳/` 按清单手工移动回原路径。 |
| 生成 inline diff 后无法写入 | 先确认每个差异块都已选择“采用此块”或“保留原文”；如果提示源文件已变化，保存当前稿后重新生成 diff。 |
| 后台任务一直显示运行中 | 等待当前模型调用返回；取消按钮只能请求取消，不能强制中断供应商已接收的 HTTP 请求。若模型长期无响应，可重启 WebUI，确认没有重复触发任务。 |
| 后台任务完成但前台没变化 | 看侧边栏「站内信」或 `AI任务 / 后台消息`；后台只推送提示，不强制刷新页面。需要查看落盘结果时进入对应页面或点击重新读取。 |
| AI 自动推进中断 | 查看 `05_项目管理/AI推进断点/第NNN章.json` 的 `last_action/last_status/last_message`。若每卷第一章停在 `generate_volume_outline`、`review_volume_outline` 或 `improve_volume_outline`，优先检查 `01_大纲/卷纲/第NN卷.md`、`AI审查缓存/outline_outline_卷纲_*.md` 和模型返回内容；修正后再次点击会按当前文件状态续接。 |
| 设置页找不到某个模型项 | 设置页会隐藏未被写/策/改/审路由选中的供应商。先在“模型与运行模式”把对应角色切到该供应商，模型项会自动显示。 |
| 恢复备份后发现不是想要版本 | 当前文件在恢复前已保存为 `*_pre_restore_时间戳.*`，可在 `日志 / 文件备份` 中继续恢复。 |
| 项目快照过大 | 快照默认排除 `.env`、日志、索引、回收站和自动备份目录；检查是否有大文件误放在创作目录。 |
| 场景计划生成失败或格式怪异 | 系统会自动降级到保守模板；真实模型下可降低 temperature 或改用 Mock 验收 JSON 流程。 |
| 启动包覆盖了故事规格 | 写入前会备份旧 `故事规格.md` 到 `05_项目管理/versions/`，可用版本库恢复。 |
| 草案采纳到错误文件 | 采纳前检查 WebUI 自动推断的目标文件；CLI 可用 `--adopt-target` 显式指定。 |
| 人物状态没有结构化更新 | 确认定稿命令使用 `--finalize --yes`；真实模型异常时可用 `--mock` 验证流程，系统会降级保留待确认摘要。 |
| 故事规格似乎没影响草案 | 进入 `中台 / 联动检查` 查看上游状态；确认故事规格不是占位模板，并重新生成对应 AI 草案。 |
| AI味检查或场景审稿像通用检查 | V1.7.2 后这些路径会自动读取项目轴；确认 WebUI 已重启，或用 Mock 模式重跑检查验证。 |
| 质量诊断提示任务卡对齐不足 | 先核对 `第NNN章_task_card.json` 是否正确，再看正文是否实际写出核心事件、情绪转折和章末钩子。 |
| 按反馈生成修订稿后仍低分 | 优先人工处理 forbidden、章末钩子和任务卡对齐，再重新运行 `--quality-diagnose`；不要无限循环调用模型。 |
| 写到几十章后故事漂移 | 检查 `01_大纲/卷纲/` 是否存在并已写清每卷主冲突、伏笔预算和卷末状态；修改后重跑 `--reindex`。 |

V2.3 策划独立路由与项目轴补强：

- 新增 `NOVEL_ASSIST_PROVIDER` 和 `NOVEL_OPENROUTER_ASSIST_MODEL`，策划辅助（世界观/总纲/角色/章纲生成）走独立路由，不再占用写正文模型。
- `audit_logic()` 和 `review_*` 审稿函数内部自动注入项目轴，无需手工传递上游设定。
- 写/策/改/审四角色完全独立：写(PROSE)、策(ASSIST)、改(REVISE)、审(CRITIC)。
- 角色档案唯一性：新角色草案自动归档旧草案，官方档案页检测重复文件。
- 角色档案升级：结构化规格对齐表 + 四阶段弧线 + 关系钩子。
- 世界观/大纲 AI 审查 + 改稿：审查结果暂存，改稿保存到 AI草案。

V2.8 戏剧诊断与风格样本：

- 完整流水线会自动生成戏剧诊断 `04_审核日志/第NNN章_戏剧诊断.json` 和 `.md`。
- 在 WebUI 写作页右栏可查看压力/弧光/画面雷达图和改稿建议。
- 风格样本从文风档案/样本池/种子库/已定稿章节中选取，自动注入 prose 生成 prompt。
- `prompts/style_seed_library.md` 内置 8 段教学样本，可按需编辑。

V3.0 写作台三栏布局：

- 写作页采用三栏：左栏章节列表+状态+技巧焦点，中栏正文+主操作按钮，右栏诊断面板。
- 主操作 3 按钮（流水线/改稿/定稿）始终可见，系统根据诊断分数自动高亮推荐。
- 戏剧诊断雷达默认展开，每条改稿建议带「采纳此改法」按钮，一键生成辅助稿。

V3.1 诊断趋势：

- 仪表板显示跨章节戏剧趋势（压力/弧光/画面均值、滚动均值、趋势方向）。
- `compute_drama_trends()` 从已有诊断 JSON 聚合计算，不额外调用模型。

V4.0 写作质量升级：

- 编辑备忘录：所有诊断跑完后自动合成，写作页右栏优先展示 top-3 改稿行动项（优先级+来源+改法+验收），每条带「采纳此改法」。
- 角色声音指纹：纯本地分析，写作页修订对比 tab 展示 unified diff；声音同质化（相似度 >70%）会标记到诊断面板。
- 技巧驱动：任务卡编辑器可选 9 种写作技巧焦点（`technique_focus`），生成正文时作为硬指令注入；场景类型自动推荐技巧。
- 正文编辑区：写作页中栏正文 tab 支持直接编辑（text_area 600px）+ 保存按钮；编辑区下方提供 AI 辅助润色（起止行 + 6 种动作 + 单段改写）。
- 健康热力图：仪表板三色方块概览各章质量状态（绿≥80/黄≥60/红<60），点击方块跳转对应章写作页。
- 场景级诊断：`run_scene_review()` 自动触发纯规则场景诊断（冲突可见性/动作密度/对白推进），诊断结果写入 ScenePlan 和 JSON 文件。

V5.0-alpha2 章节模式、风格档案与作家豁免：

- 任务卡支持 `chapter_mode`、`ending_style`、`pacing`、`style_profile`。可在 WebUI `大纲 / 任务卡 / V5.0 章节口径` 调整。
- 项目默认风格档案可在 WebUI 设置页保存为 `NOVEL_STYLE_PROFILE`；单章任务卡的 `style_profile` 优先级更高。
- 内置风格档案：`jin_yong`（金庸）、`wang_xiaobo`（王小波）、`yu_hua`（余华），样本为原作实录选段。用户可在 WebUI 设置页「风格档案管理」新增/编辑/删除自定义档案，持久化到 `05_项目管理/style_profiles.json`。
- 三态裁决（V5.0-rc1）：每条诊断 finding 支持「采纳」（保留，不退分）、「保护」（豁免，退分）、「反驳」（驳回，退分）。裁决面板统一覆盖质量诊断、风格法庭 contested、文学风险和编辑备忘录。记录写入 `04_审核日志/第NNN章_诊断豁免.json`。
- 重新运行质量诊断后，被保护/反驳的 finding 不再进入改稿清单、质量 revision brief 或编辑备忘录必改项；被采纳的保持活跃。
- 若要验证附录 B.1/B.2，请将任务卡标为 `chapter_mode=atmosphere|interior`、`ending_style=open|echo`、`pacing=slow_burn`，再运行 `python novel_pipeline.py --chapter N --quality-diagnose`。

V5.0-beta1 写作表面：

- WebUI `全书 / 写作` 默认显示单栏稿纸；章节命令、AI 助手和诊断抽屉通过顶部按钮或快捷键唤出。
- 快捷键：`Ctrl/Cmd+P` 打开章节命令，`Ctrl/Cmd+.` 打开诊断抽屉，`Ctrl/Cmd+K` 打开 AI 助手，`Ctrl/Cmd+Enter` 保存当前稿纸，`Ctrl/Cmd+Shift+F` 切换专注写作。
- 质量诊断会被整理为最多 5 条页边批注；点击「不用」会直接写入作家豁免，下次诊断后不再进入扣分和改稿 prompt。
- WebUI `全书 / 全书概览` 的章节健康图已改成卷轴色带。越浅越稳，越深越值得回看；不再使用红黄绿方块。

V5.0-beta2 文学批评层与风格法庭：

- 单独生成当前稿的 LiteraryView 和 style_court：

```bash
python novel_pipeline.py --chapter 1 --literary-critic --mock
```

- 完整流水线和 `--revise-from-feedback` 会在质量诊断后写入 `04_审核日志/第NNN章_文学批评.*`、`第NNN章_风格法庭.*` 和更新后的 `第NNN章_编辑备忘录.*`。
- LiteraryView 不打分，只记录可记忆瞬间、未说之语、读者残响、文学风险和 `cannot_be_quantified`；Mock 结果只能做离线验收，不代表真实文学判断。
- style_court 的 `confirmed_issues` 可以进入编辑备忘录必改项；`contested_issues` 会进入 reservations，不得被改稿 prompt 执行。
- 验证附录 B.1：让章节含有”被压扁的眼睛”等意象，任务卡标为 `chapter_mode=atmosphere` 后运行文学批评，确认冲突/身体情绪类建议进入 contested，而任务卡/forbidden 硬约束仍 confirmed。

V5.0-rc1 三态裁决、文学批评面板与三维项目健康：

- 写作页诊断抽屉（`Ctrl/Cmd+.`）改为标签页：文学批评（默认）/ 工程诊断 / 风格法庭 / 备忘录。文学批评完整展示全部 LiteraryView 字段。
- 每条诊断 finding 旁有三个裁决按钮：「采纳·下次改」「保护·不改」「反驳·误判」，点击后弹出理由输入框，确认后写入诊断豁免。
- 仪表板「全书概览」显示三个独立健康指标（工程稳健度/文学密度/风格一致度），各自有趋势箭头和弱章提示。
- 卷轴健康图支持三维切换：默认工程稳健度色带，可切换查看文学密度或风格一致度。
- 风格档案为项目级持久化配置；WebUI 设置页可新增自定义作家档案、覆盖内置默认字段、删除自定义档案。

V5.0-UX 块级 diff、后台任务与自动推进：

- inline diff 不再整稿一键覆盖。写作 AI、单段润色、备忘录改稿、戏剧建议改稿生成的预览都会拆成差异块，逐块采用/保留后才写入。
- 主要 LLM 长任务通过 `webui_infra/background_jobs.py` 执行：写作 AI、智能推荐动作、流水线、逐步审计、场景生成/审稿、世界观/大纲/启动包 AI 生成与改稿。任务条显示进度和取消请求。
- 写作页 `AI 自动推进当前章` 会自动串联章纲生成/采纳、每卷第一章卷纲生成/审查/改稿、章纲审查、章纲改稿、任务卡、场景计划、场景草稿、章节草稿、审计、AI味、读者镜像、深度检查、质量诊断、反馈修订和定稿记忆。卷内后续章节不重复处理卷纲；失败时记录断点，下次点击从当前文件状态续接。
- 后台任务完成后写入站内信并 toast 提醒，不强制刷新正在编辑的前台页面。
- 2026-05-07 删除了旧测试用第 001 章；如果验收脚本或手工流程需要样例章，请新建合法章节，不要恢复旧 001 测试资产。
