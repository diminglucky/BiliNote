# VideoNote

VideoNote 是一个面向视频学习的 AI 笔记工具。它把视频链接或本地视频整理成结构化 Markdown 笔记，并配合关键截图、思维导图和问答能力，让内容更容易复习、整理和二次使用。

当前版本：`0.2.2`

## 主要能力

- 支持 Bilibili、YouTube、Douyin、Kuaishou 和本地视频
- 自动下载、转写、总结并生成 Markdown 笔记
- 支持按内容插入关键截图，而不是只给纯文本
- 支持思维导图预览与导出
- 支持基于笔记和转写内容继续问答
- 支持浏览器扩展快速生成笔记
- 支持 Tauri 桌面端
- 支持模型供应商、转写器、代理和下载 Cookie 配置

## 目录说明

- `backend/`：FastAPI 后端，负责下载、转写、截图、生成与导出
- `BillNote_frontend/`：React 前端，负责任务提交、笔记预览、设置和导出
- `BillNote_extension/`：浏览器扩展，支持在视频页快速发起生成
- `start-dev.bat`：Windows 一键启动后端和前端

## 快速开始

### 环境要求

- Python 3.11
- Node.js 20+
- pnpm
- FFmpeg
- Windows 下建议使用 Anaconda 环境 `play`

### 一键启动

直接运行根目录下的 `start-dev.bat`。

- 后端默认地址：`http://127.0.0.1:8483`
- 前端默认地址：`http://127.0.0.1:3015`

### 手动启动后端

```bash
cd backend
pip install -r requirements.txt
python main.py
```

### 手动启动前端

```bash
cd BillNote_frontend
pnpm install
pnpm dev
```

### 启动浏览器扩展

```bash
cd BillNote_extension
pnpm install
pnpm dev
```

构建完成后，在浏览器扩展页面加载 `BillNote_extension/extension/`。

### 启动桌面端

桌面端基于 Tauri。

```bash
cd backend
# 按项目现有脚本构建后端二进制

cd ../BillNote_frontend
pnpm tauri dev
```

正式打包使用：

```bash
cd BillNote_frontend
pnpm tauri build
```

## 配置说明

项目根目录提供了 `.env.example`，常用配置包括：

- 后端端口、前端端口
- FFmpeg 路径
- 截图输出目录
- 转写器类型与模型大小
- 截图审查模式与候选数量
- 视频下载代理配置

说明：

- LLM 的供应商和模型通常在前端“设置”中配置
- 部分平台需要 Cookie 才能下载或解析
- 截图与导出文件会保存在后端配置目录中

## 常见输出

- Markdown 笔记
- ZIP 导出
- PDF / DOCX / HTML 等导出格式
- 思维导图文件

## 开发提示

- 后端默认监听 `8483`
- 前端开发端口默认 `3015`
- 需要本机可用的 FFmpeg
- 如果遇到视频平台下载失败，优先检查 Cookie 和代理配置

## 许可证

MIT License。另请查看仓库中的 `LICENSE` 和 `NOTICE`。
