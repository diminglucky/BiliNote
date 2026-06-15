# VideoNote

VideoNote 是一个面向视频学习的 AI 笔记工作台。它把视频链接、本地视频、转写文本和关键画面整理成可复用的结构化笔记，适合课程学习、教程复盘、技术演示归档和长视频知识提炼。

这个项目的重点不是简单摘要，而是“先形成可读笔记，再按内容补齐合适图片”：正文优先交付，截图异步增强，最终输出更接近能直接写进知识库的学习资料。

## 核心能力

- 支持 Bilibili、YouTube、抖音、快手和本地视频
- 支持 FastAPI 后端、React 前端和 Tauri 桌面端
- 支持 OpenAI 兼容模型供应商配置
- 支持 Fast-Whisper、Groq、BCut、快手等转写方式
- 支持先生成 Markdown，再异步插入关键截图
- 支持截图 agent 过滤空白页、片尾页、无关页面和重复画面
- 支持生成思维导图、导出笔记和基于笔记内容问答

## 开发启动

### 后端

```bash
cd backend
pip install -r requirements.txt
python main.py
```

默认后端地址：`http://127.0.0.1:8483`

### 前端

```bash
cd BillNote_frontend
pnpm install
pnpm dev
```

默认前端地址：`http://127.0.0.1:3015`

### Docker

```bash
docker-compose up
```

GPU 版本：

```bash
docker-compose -f docker-compose.gpu.yml up
```

### 浏览器插件

```bash
cd BillNote_extension
pnpm install
pnpm dev
```

构建后在浏览器扩展页面加载 `BillNote_extension/extension/`。

## 项目结构

- `backend/`：FastAPI 后端，负责下载、转写、截图、笔记生成和任务管理
- `BillNote_frontend/`：React + Vite 前端，负责任务提交、预览、设置和桌面端界面
- `BillNote_extension/`：浏览器插件，负责在视频页快速提交任务
- `backend/app/services/visual_screenshot_agent.py`：截图选择与视觉评审逻辑
- `backend/app/services/visual_screenshot_graph.py`：截图增强 workflow

## 版本

当前应用版本见 `BillNote_frontend/package.json`。

## License

MIT License. 开源来源与许可证说明见 [NOTICE](./NOTICE)。
