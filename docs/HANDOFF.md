# 阶段交接

日期：2026-05-07

## 已完成
- 建立本地长篇小说创作流水线：RAG 上下文、正文生成、逻辑审计、AI 味检查、定稿和滚动记忆更新。
- 增加 Mock 模式和单元测试，支持无 API Key 的完整验收。
- 增加结构化章节流程：任务卡、确认、场景计划、场景候选稿、审稿、版本选择、合并章节草稿。
- 增加 V1.0 项目中台：`05_项目管理/`、项目状态 JSON、任务队列和质量报告。
- 增加 WebUI 工作台：根据章节状态推荐下一步。
- 增加 OpenRouter 支持：正文和审计均可切换，WebUI 会自动补 `anthropic/` 前缀。
- 增加世界观、大纲、章纲、单角色和批量角色 AI 辅助草案。
- 增加章节安全删除：WebUI 和 CLI 都移动到 `99_回收站/`。
- 增加 WebUI 自动保存：Markdown/JSON 编辑区支持 Ctrl+Enter/apply 自动落盘。
- 增加设置页表单：参数输入框按 Enter 保存整组 `.env` 配置。
- 清理并补充项目文档：`README.md`、`AGENTS.md`、`CLAUDE.md`、`docs/ARCHITECTURE.md`、`docs/RUNBOOK.md`。
- V1.1 增加版本库与项目快照：CLI/WebUI 可列出全目录 `versions/` 备份、恢复指定备份、恢复前保护当前文件、生成项目 zip 快照。
- V1.4 增加结构化创作闭环：任务卡生成时识别隐式伏笔，场景计划由 LLM 生成，修订稿自动复审，总纲进入 RAG 索引。
- V1.5 增加启动向导与草案采纳：类型预设、启动包生成、AI 草案采纳、占位符补全建议。
- V1.6 增加人物状态与伏笔长期维护：定稿后抽取人物状态增量，写入 `人物状态表.md`/`人物状态.json`，伏笔表自动升级七列。
- V1.7 增加模块联动增强：世界观、总纲、角色、批量角色和章纲 AI 辅助统一注入项目轴；中台新增联动检查。
- V1.7.1 加强可见联动：策划 prompt 强制“项目规格对齐”，草案落盘自动补联动头，Mock 世界观会根据当前故事规格生成。
- V1.7.2 补强后期链路联动：AI味/文风检查、场景审稿、人物状态维护、伏笔识别和场景计划都读取项目轴。
- V1.8 增加章节质量诊断：本地检查节奏、对白、句长、套话、重复片段、章末钩子和任务卡对齐；CLI、完整流水线、WebUI 写作页和工作台推荐已接入。
- V1.9 增加诊断驱动改稿：质量诊断参与修订判断，审计、AI味和诊断合成改稿指令，修订后自动复审并重跑质量诊断。
- V2.0 增加长篇结构层：新增卷/幕结构模板、当前卷上下文注入、卷纲进 RAG、WebUI `大纲 / 卷/幕` 管理和健康检查/质量报告联动。
- V2.3 策划独立路由与项目轴补强：写/策/改/审四角色独立路由（新增 `NOVEL_ASSIST_PROVIDER` + `NOVEL_OPENROUTER_ASSIST_MODEL`）；`audit_logic()` 内部自动注入项目轴；`review_*` 函数通过 `add_project_linkage()` 注入项目轴；角色档案唯一性（新草案自动归档旧草案、官方档案页检测重复）；角色档案升级为改进版（结构化规格对齐表 + 四阶段弧线 + 关系钩子）；世界观/大纲 AI 审查 + 改稿。
- V2.4 前端集成优化：写作页按钮融合（7→智能推荐+折叠区）、审核标签合并（4→1 含子标签）、Mock 全局化侧边栏、健康检查并入日志、导航 9→8 项。后端零改动。
- V2.8 戏剧结构诊断与风格样本注入：`dramatic_arc_diagnostics.py`（压力/弧光/画面三轴诊断，CRITIC_PROVIDER），`prompts/style_seed_library.md`（8 段教学样本），`inject_prose_samples` 注入正文生成 prompt，14 个单元测试。
- V3.0 写作台三栏重构：`webui_infra/` 模块包（navigation/state/pages/writing），三栏布局（1:3:2），戏剧雷达默认可见+「采纳此改法」按钮，主操作 3 按钮智能高亮推荐，webui.py 4291→3901 行。
- V3.1 诊断趋势统计：`DramaTrends` 跨章滚动均值，`trend_direction` 趋势方向，仪表板戏剧趋势区块可视化。
- V4.0 写作质量与操作体验升级：编辑备忘录 `editor_memo.py`（6诊断→1备忘录，prompt 压缩 80%）、角色声音指纹 `voice_diagnostics.py`（零 API 对白区分）、技巧驱动生成 `technique_focus`（9 种硬指令）+ 正文编辑区 `st.text_area` + 6 种 AI 润色、健康热力图 `_render_chapter_health_heatmap()` + 场景级纯规则诊断 `_diagnose_scene_locally()`。新增 101 测试，290 测试通过。
- V5.0-alpha1 建立 V5 升级计划和附录必读机制：`docs/V5.0_UPGRADE_PLAN.md`、`docs/V5.0_DESIGN_SOUL_APPENDIX.md`、`docs/V5.0_ALPHA1_APPENDIX_RECHECK.md`；WebUI 默认进入“今天”，mock 文学评估警示、score caveat、inline 改稿预览、供应商测试补强。
- V5.0-alpha2 增加章节模式、风格档案和作家豁免：`ChapterTaskCard.chapter_mode/ending_style/pacing/style_profile`，`style_profiles.py` + `prompts/style_profiles/`，按 mode 诊断阈值，writer overrides 写入 `04_审核日志/第NNN章_诊断豁免.json`，EditorMemo reservations 禁止被保护建议进入改稿 prompt。
- V5.0-beta1 增加单栏稿纸、页边批注、快捷键桥和卷轴健康图：`webui_infra/components/keyboard.py`、`margin_notes.py`、`scroll_health.py`；写作页默认聚焦正文，命令/AI/诊断改为唤出式面板，全书健康图替换红黄绿方块。
- V5.0-beta2 增加文学批评层与风格法庭：`literary_critic.py` + `prompts/文学批评.md` 生成 LiteraryView，`style_court.py` 将工程诊断裁决为 confirmed/contested/literary priorities；完整流水线、`--revise-from-feedback`、`--literary-critic` 和 WebUI 诊断抽屉已接入，contested 自动进入 EditorMemo reservations。
- V5.0-rc1 增加三态作家裁决、文学批评独立面板、三维项目健康与风格档案 WebUI 管理：`DiagnosticReservation.action` 支持 adopt/protect/rebut 三分支；诊断抽屉改为标签页结构（文学批评/工程诊断/风格法庭/备忘录）；`ProjectHealthSnapshot` 以工程稳健度/文学密度/风格一致度三指标替代单分；WebUI 设置页新增风格档案管理（增删改查持久化到 `05_项目管理/style_profiles.json`）；三个内置作家样本替换为原作实录选段。全量 410 项测试通过。
- V5.0-UX 收口完成：对照初始 UX 设计稿，删除旧测试用第 001 章并移入 `99_回收站/第001章_20260507_013144/`；写作页 inline diff 升级为差异块逐块采用/保留；主要 LLM 长任务接入 `webui_infra/background_jobs.py` 后台任务条。
- V5.0-UX 继续收口：WebUI 顶层入口调整为 `写作`、`故事圣经`、`规划`、`AI任务`、`设置`；写作页新增 `AI 自动推进当前章`，自动串联章纲生成/采纳、每卷第一章卷纲生成/审查/改稿、章纲审查、章纲改稿、任务卡、场景、草稿、审计、检查、修订和记忆更新，并将断点写入 `05_项目管理/AI推进断点/第NNN章.json`；后台任务完成通过站内信和 toast 提醒，不强制刷新前台；设置页只显示当前启用供应商并多列紧凑排布。

## 验收记录
2026-05-05 已执行：

```bash
python -m py_compile novel_schemas.py structured_store.py llm_router.py quality_diagnostics.py long_structure.py workflow_advisor.py prompt_assembly.py novel_pipeline.py webui.py tests\test_pipeline.py
python -m unittest discover -s tests -v
```

结果：290 项单元测试通过；WebUI 本地服务返回 200。

2026-05-06 V5.0-beta2 已执行：318 项单元测试通过。

2026-05-07 V5.0-rc1 已执行：

```bash
python -m unittest discover -s tests -v
```

结果：410 项单元测试通过（新增 test_v5_rc1_data_layer 38 + test_v5_rc1_pipeline 27 + test_v5_rc1_integration 27 = 92 项 rc1 专项测试）。

2026-05-07 V5.0-UX 收口后已执行：

```bash
python -m py_compile webui.py webui_infra/pages/writing.py webui_infra/background_jobs.py
python -m unittest tests.test_webui_infra tests.test_pipeline.WebUIHelperTests -v
python -m unittest discover -s tests -v
```

结果：413 项单元测试通过；Streamlit 烟测 `http://localhost:8509` 返回 200；`01_大纲/章纲`、`02_正文`、`04_审核日志` 未发现 `第001章*` 残留测试章节文件。

2026-05-07 设置页与写作自动推进小步修复已执行：

```bash
python -m py_compile webui.py
python -m unittest tests.test_pipeline.WebUIHelperTests tests.test_webui_infra -v
```

结果：40 项 WebUI/基础设施相关测试通过。此次仅覆盖小范围回归；完整发布前仍应跑 `python -m unittest discover -s tests -v`。

## 接手建议
1. 先运行 `python -m unittest discover -s tests -v`，确认基础行为仍然稳定。
2. 打开 WebUI 的 `设置 / 日志 / 健康检查` 页面，确认本机模型、Ollama、RAG、任务卡状态。
3. 使用 Mock 模式验收世界观 AI 辅助、批量角色草案、任务卡、场景流程、章节删除。
4. 真实调用前检查 `.env`，尤其是供应商、模型 ID 和 API Key。
5. 章节进入正式写作前，先补齐 `00_世界观/世界观.md`、`00_世界观/文风档案.md`、`01_大纲/总纲.md` 和目标章节章纲，避免占位符进入正文。
6. 重要修改前可在 WebUI `日志 / 项目快照` 或 CLI `--snapshot-project` 生成项目快照。
7. V1.4 后建议先用 `--plan-card --mock` 与 `--plan-scenes --mock` 验证结构化 JSON，再切真实模型。
8. V1.5 后新项目可先在 `中台 / 启动向导` 生成启动包，再逐份采纳 AI 草案。
9. V1.6 后每章定稿后检查 `记忆 / 结构化记忆`，确认人物状态 JSON、伏笔 JSON 和章节记忆 JSON 同步生成。
10. V1.7 后如果用户觉得上游设定没影响下游，先看 `中台 / 联动检查`，再重跑对应 AI 草案。
11. V1.8 后 AI 味检查完成后应补一次 `--quality-diagnose` 或使用 WebUI `写作 / 质量诊断`，重点看 forbidden 命中、章末钩子和任务卡对齐。
12. V1.9 后若质量诊断低分或高风险，可运行 `python novel_pipeline.py --chapter N --revise-from-feedback --mock` 验证改稿闭环，再切真实模型。
13. V2.0 后进入长篇写作前先运行 `python novel_pipeline.py --init-volumes --volume-count 3` 或在 WebUI `大纲 / 卷/幕` 初始化卷纲，再重建 RAG。

## 注意事项
- 目前 `.env` 是本地秘密文件，不应提交。
- `versions/` 是自动备份目录，不应当作为代码资产提交。
- `99_回收站/` 是安全删除恢复区，不应当作为代码资产提交。
- `06_项目快照/` 是本地快照输出目录，不应当作为代码资产提交。
- OpenRouter 调 Claude 系列模型时需要 `anthropic/` 前缀；WebUI 保存配置会自动补齐，CLI 直接读 `.env`。
- WebUI 以本地文件为准，没有独立数据库；刷新后是否保留内容取决于是否已落盘。
- 用户已经要求“所有页面内容修改 apply 后自动保存”，后续新增编辑器时应复用 `_md_editor` 或 `_json_file_editor`。
- 备份恢复会覆盖目标文件，但恢复前会先把当前目标文件保存为 `*_pre_restore_时间戳.*`。
- 场景计划优先走 LLM；如果真实模型返回非 JSON，系统会降级到固定保守模板，保证流程不中断。
- 草案采纳会写入正式文件，采纳前会先备份旧文件；WebUI 会显示自动推断的采纳目标，不再要求手输确认文字。
- 人物状态抽取优先走 LLM；异常时定稿流程会保留旧的待确认摘要，不阻断正文定稿。
- 前期策划辅助不应再直接拼局部模板；新增辅助入口时必须复用 `build_planning_context()` 或 `append_planning_context()`。
- 章节质量诊断是本地启发式检查，不替代 LLM 逻辑审计；它适合做改稿优先级排序，尤其是节奏、套话和任务卡执行情况。
- 诊断驱动改稿会调用改稿模型；真实模式下应先确认质量报告确实需要修订，避免把轻微风格偏好变成重复模型调用。
- 卷纲属于上游结构约束；修改 `01_大纲/卷纲/` 后应重建 RAG，并在 `中台 / 联动检查` 确认卷/幕结构已进入正文生成链路。
- V2.3 起策划辅助走 `NOVEL_ASSIST_PROVIDER` 独立路由，与正文写作模型分开；设置页三栏（写/策/改/审）各自独立选择供应商和模型。
14. V2.8 后完整流水线会自动生成戏剧诊断；在 WebUI 写作页右栏可查看雷达图和改稿建议，每条建议带「采纳此改法」按钮。
15. V3.0 后写作页采用三栏布局：左栏章节列表+技巧焦点，中栏正文+操作，右栏诊断面板。可编辑正文的 text_area 支持直接修改并保存。
16. V4.0 后写/审/改链路完整：先跑流水线生成所有诊断，写作页右栏编辑备忘录给出 top-3 优先改项；正文编辑区下方可使用 6 种 AI 润色动作；提示角色声音同质化时优先区分两人用词/句长/语气词；仪表板健康热力图可概览各章质量状态。
17. V5.0+ 后每次升级前必须先读 `docs/V5.0_DESIGN_SOUL_APPENDIX.md`；alpha2 已支持在任务卡设置 ChapterMode/StyleProfile，并可把误伤文学性的诊断标为作家豁免。
18. V5.0-beta1 后写作页默认不再是三栏驾驶舱；需要旧式批量操作时点顶部「更多」，需要诊断时点「诊断」或按 `Ctrl/Cmd+.`。
19. V5.0-beta2 后改稿前应先看风格法庭：`confirmed_issues` 才能进入必改，`contested_issues` 代表文学保护，不应被换说法塞回改稿 prompt。
20. V5.0-rc1 后诊断抽屉默认打开文学批评标签页，工程指标在后；每条 finding 有三态裁决按钮，裁决是作家的事，诊断只提供参考。
21. V5.0-UX 收口后 inline diff 必须逐块裁决，不能回退为整稿一键覆盖；主要 LLM 长任务应通过后台任务条启动，取消按钮是尽力请求，不能强制中断已发出的供应商 HTTP 调用。
22. 写作页应优先通过 `AI 自动推进当前章` 顺着实际写作流程推进，不要让用户在集中 AI 页、卷纲页、章纲页和写作页之间来回切换；每卷第一章的卷纲生成/审查/改稿、章纲审查和章纲改稿必须位于任务卡前，卷内后续章节不重复阻塞卷纲。
23. 设置页应保持“按当前路由显示”的紧凑形态：未启用供应商模型项自动隐藏，常用参数多列排布；修复 Streamlit 重复元素时优先补显式 `key`，不要退回一行一个参数。
24. 旧测试用第 001 章已删除到回收站；后续验收若需要样例章节，应新建合法章节，不要恢复旧测试资产。当前项目可以再次拥有正式的 `第001章*` 文件，不能仅凭章号判断为测试污染。
