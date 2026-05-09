# V3 分阶段迭代路线图

> 来源：`docs/V3.0_UPGRADE_BLUEPRINT.md`
> 目标：把一次性 V3.0 大改拆成可独立验收、可独立回滚的小版本，持续围绕两条主线推进：
> 1. 写出更好看的长篇中文小说
> 2. WebUI 更集成、更少点击、更容易闭环

---

## 版本拆分总览

| 版本 | 主题 | 蓝图对应 | 交付边界 | 验收 |
|---|---|---|---|---|
| V2.6 | 风格样本注入 | P0-B | 内置中文写作技巧样本库；正文 prompt 自动注入用户样本/定稿样本/种子样本；CLI 可打印 prompt 验证 | 第 1 章 mock prompt 出现 3 段带技巧标签的文风样本 |
| V2.7 | 戏剧诊断模型骨架 | P0-A 2.1-2.4 | 新增 schema、prompt、`dramatic_arc_diagnostics.py`；独立 CLI 可 Mock 诊断并落盘 JSON/Markdown | `--dramatic-diagnose --mock` 跑通 |
| V2.8 | 戏剧诊断接入写作闭环 | P0-A 2.5-2.7 | 完整流水线自动接入；改稿 prompt 优先注入戏剧诊断；联动检查提示缺诊断章节 | 修订 prompt 含“戏剧诊断改稿任务” |
| V2.9 | WebUI 拆包准备 | P0-C 3.1-3.2 | `webui/` 包、theme/state/components/pages 基础设施；旧页面平迁，行为不变 | Streamlit 启动正常，8 项导航不变 |
| V3.0 | 写作页三栏重写 | P0-C 3.3-3.6 | 写作页三栏主工作台；戏剧雷达、改稿建议、主操作按钮常驻；高频路径压到 3 步 | 从进入写作页到采纳改法 ≤ 3 步 |
| V3.1 | 诊断样本闭环强化 | P0-B/P0-A 后续 | 高 cinematic_score 定稿段落进入样本池；样本锁定/排除；诊断趋势统计 | 第 6 章后优先抽高分定稿样本 |

---

## V2.6：风格样本注入

**为什么先做**

这是收益最高、风险最低的一步。它不改变文件状态机，也不改 WebUI 主流程，只增强正文生成的 system prompt，让模型在冷启动时看到“什么是好句子”。

**范围**

- 新建 `prompts/style_seed_library.md`
- `prompt_assembly.py` 新增：
  - `inject_prose_samples()`
  - `_load_seed_library()`
  - `_load_user_style_samples()`
  - `_sample_from_finalized_chapters()`
- `render_prose_system_prompt(project_dir, current_chapter_num=1)` 支持按章号注入样本
- CLI 增加 `--print-prompt`，用于验证 prompt
- 章节完整流水线、反馈修订、场景草稿、WebUI 正文生成均传入章节号

**不做**

- 不引入戏剧诊断 schema
- 不改 WebUI 布局
- 不读取真实 LLM 日志明文

**验收命令**

```bash
python -m unittest tests.test_pipeline.PromptAssemblyTests -v
python novel_pipeline.py --chapter 1 --print-prompt --mock
```

---

## V2.7：戏剧诊断模型骨架

**范围**

- `novel_schemas.py` 新增戏剧诊断模型
- 新建 `prompts/戏剧诊断.md`
- 新建 `dramatic_arc_diagnostics.py`
- Mock 模式可生成确定性的诊断报告
- 解析 LLM JSON 响应，失败降级 Mock 并记录原文
- CLI 新增独立 `--dramatic-diagnose`，用于单章手动诊断验收

**不做**

- 暂不接入完整流水线自动步骤
- 暂不把戏剧诊断改稿任务注入 `--revise-from-feedback`
- 暂不改 WebUI

**验收命令**

```bash
python -m unittest tests.test_dramatic_diagnostics -v
python novel_pipeline.py --chapter 1 --dramatic-diagnose --mock
```

---

## V2.8：戏剧诊断接入写作闭环

**范围**

- `novel_pipeline.py` 新增：
  - `--skip-drama-diagnose`
- 完整流水线：最终草稿/修订稿质量诊断后追加戏剧诊断
- `--revise-from-feedback`：优先读取戏剧诊断；若不存在则补生成，并把“戏剧诊断改稿任务”放在改稿 prompt 顶部
- `project_center.py`：定稿/草稿缺戏剧诊断时给出健康提示

**不做**

- 不重写 WebUI
- 不改变旧 `quality_diagnostics.py`

**验收命令**

```bash
python -m unittest tests.test_pipeline.PipelineHelperTests -v
python -m unittest tests.test_dramatic_diagnostics -v
python novel_pipeline.py --chapter 1 --mock
```

---

## V2.9：WebUI 拆包准备

**范围**

- 先建立不与 `webui.py` 冲突的 `webui_infra/` 基础包
- 抽出 session_state 默认值和导航常量
- 旧页面仍由 `webui.py` 承载，保证行为不变
- 后续壳化时再处理 `webui.py` 与最终 `webui/` 包的命名切换

**不做**

- 不在这一版做三栏重写
- 不改变导航结构

**验收命令**

```bash
python -m unittest tests.test_webui_infra -v
python -m unittest discover -s tests -v
```

---

## V3.0：写作页三栏重写

**范围**

- 写作页改为左章表、中稿件、右诊断建议
- 雷达图和改稿建议默认可见
- 主按钮常驻：流水线、改稿、定稿、保存
- “采纳此改法”走局部保守改稿

**完成定义**

- 打开 WebUI 到看到建议无需展开折叠区
- 从写作页到采纳一条改法不超过 3 步
- 子报告仍可查看，但默认收起

---

## 发布纪律

- 每个版本单独 commit，可独立 revert
- 每版至少跑：

```bash
python -m unittest discover -s tests -v
```

- 涉及 CLI 的版本补一条 mock 验收命令
- 涉及 WebUI 的版本启动 Streamlit 手动检查
