# VideoNote Agent 重构方案

## 目标

把当前生成链路重构成“总调度器 + 专项子 agent + 动态工作流”。

核心目标：

- 先出可读 Markdown，再按需补图
- 降低不必要的多模态调用
- 保留现有兼容行为，逐步迁移，不一次性推翻
- 让每一步都有明确状态、日志和失败降级

## 现状

当前项目里已经存在几类职责：

- `NoteGenerator`：总入口，负责下载、转写、总结、后处理
- `VisualScreenshotAgent`：截图规划、候选筛选、视觉复审、插图
- `VisualEnhancementService`：基于已保存笔记异步补图
- `chat_service`：基于向量检索的问答

这套结构已经接近 agent 化，但职责还不够清晰，尤其是 `NoteGenerator` 仍然承担了太多编排细节。

## 新架构

### 1. Orchestrator

`NoteGenerator` 只做调度，不做具体决策细节。

职责：

- 读取配置
- 决定是否需要下载、转写、写作、截图、问答索引
- 组装执行计划
- 收集各 sub agent 的结果
- 更新任务状态

### 2. Sub Agent

按能力拆分：

- `DownloadAgent`
- `TranscriptAgent`
- `NoteWriterAgent`
- `VisualPlannerAgent`
- `FrameSelectorAgent`
- `VisionReviewAgent`
- `MarkdownComposerAgent`
- `MindMapAgent`
- `ChatRagAgent`

### 3. Workflow

主链路串行，局部并行：

```text
下载/字幕
  ↓
转写
  ↓
生成 Markdown
  ↓
视觉规划
  ↓
并行处理多个截图 slot
  ↓
合成 Markdown / 保存 / 索引
```

## 动态规则

不是每次都启用所有 agent，而是根据任务需求动态激活：

- 无字幕时才启用转写兜底
- 不勾选截图时跳过视觉链路
- `SCREENSHOT_REVIEW_MODE=off` 时跳过多模态复审
- 笔记已经足够清晰时，减少截图 slot
- 章节信息密度高时，允许同一章节多个 slot

## 并行边界

可以并行：

- 多个截图 slot
- 候选帧本地评分
- 问答索引构建
- 导出准备

必须串行：

- 下载在前，转写在后
- 转写在前，写作在后
- Markdown 规划在前，插图在后
- 最终合成在所有 slot 完成后

## 分阶段落地

### Phase 1

- 引入 `agent` 目录与公共契约
- 为任务生成一个 `ExecutionPlan`
- 把截图流程包装成可复用的 workflow
- 保持旧接口不变

### Phase 2

- 拆出下载、转写、写作子 agent
- `NoteGenerator` 只保留编排逻辑
- 增加更多状态和诊断信息

### Phase 3

- 扩展更完整的动态工作流
- 将问答、导出、导图也纳入统一调度

## 风险控制

- 任何新架构都必须保留现有结果文件格式
- 任何新 agent 都必须有降级路径
- 截图失败不能导致整篇笔记失败
- 多模态失败不能阻塞基础 Markdown 输出

## 预期收益

- 更快出首版笔记
- 更少无效 API 调用
- 更容易定位慢点和失败点
- 更方便继续扩展真正的多 agent 协作
