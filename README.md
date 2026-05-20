# Hermes Voice Gateway — 墨凌语音交互网关

> 让老李通过手机/桌面浏览器与墨凌进行实时语音对话
> 本项目不是独立Agent，而是墨凌的"嘴巴和耳朵"

---

## 一、项目定位

```
┌──────────────┐     WebSocket/WebRTC     ┌──────────────────┐     HTTP/OpenAI API     ┌─────────────────┐
│  手机浏览器   │ ◄════════════════════► │  Pipecat Server  │ ◄═══════════════════► │  Hermes Agent   │
│  桌面浏览器   │    音频流 (PCM/Opus)    │  (腾讯云服务器)    │   /v1/chat/completions │  (墨凌大脑)      │
│  React App   │                         │  STT → LLM → TTS  │                        │  工具/记忆/技能   │
└──────────────┘                         └──────────────────┘                        └─────────────────┘
```

**核心逻辑：**
- **Pipecat** 负责：录音(STT) → 语音识别 → 调用Hermes → 文字回复 → 语音合成(TTS) → 播放
- **Hermes Agent** 负责：理解意图、调用工具、查询记忆、执行任务（一切它现在能做的事）
- **前端** 负责：麦克风采集、音频播放、连接管理

---

## 二、技术选型

### 2.1 框架选型对比

| 方案 | Stars | 优点 | 缺点 | 结论 |
|------|-------|------|------|------|
| **Pipecat** | 12.3k | 纯Python、组件化pipeline、WebSocket+WebRTC、免费STT/TTS、Voice UI Kit前端组件 | 需要自己写连接Hermes的适配 | **采用** |
| LiveKit Agents | 10.6k | 生产级WebRTC、稳定性强 | 必须跑LiveKit服务器、架构重 | 过重 |
| TEN Framework | 4k+ | 灵活、C++核心 | 文档少、社区小 | 备选 |
| Hermes CLI /voice | — | 最简单、内置 | 仅限CLI、无Web端、无手机端 | 不满足需求 |

### 2.2 STT（语音识别）

| 方案 | 成本 | 质量 | 延迟 |
|------|------|------|------|
| **faster-whisper (local)** | 免费 | base模型够用，medium优秀 | CPU ~1-2s |
| Groq Whisper | 免费额度 | 优秀 | <0.5s |
| OpenAI Whisper | 付费 | 优秀 | ~1s |

**推荐：faster-whisper 本地运行，base模型起步，零成本。**

### 2.3 TTS（语音合成）

| 方案 | 成本 | 中文质量 | 延迟 |
|------|------|----------|------|
| **Kokoro TTS (local)** | 免费 | 支持中文(Language.ZH) | 极快，本地ONNX推理 |
| edge-tts | 免费 | 好 | 网络延迟 |
| GLM TTS | API调用 | 最好 | 需联网 |

**推荐：Kokoro TTS 本地运行，完全免费零依赖，首次自动下载模型(~200MB)。**
**后续可升级到GLM TTS获得更自然语音。**

### 2.4 LLM（大模型）→ 不直接调LLM，而是调Hermes

**这是关键设计：Pipecat的LLM模块不连接任何大模型API，而是连接Hermes Agent的API Server。**

Hermes API Server 暴露 OpenAI 兼容接口：
- 地址：`http://127.0.0.1:8642/v1`
- 认证：`Bearer <API_SERVER_KEY>`
- 端点：`POST /v1/chat/completions`（标准OpenAI格式）

Pipecat 的 `OpenAILLMService` 原生支持 `base_url` 参数，直接指向 Hermes：
```python
llm = OpenAILLMService(
    api_key="change-me-local-dev",
    base_url="http://127.0.0.1:8642/v1",
    model="hermes-agent",  # Hermes的模型名
)
```

**这意味着：**
- 语音消息 → STT转文字 → 发给Hermes → Hermes回复文字 → TTS转语音 → 播放
- Hermes拥有完整上下文：记忆、技能、工具、飞书/微信消息历史
- 语音session是Hermes的又一个通道，和飞书/WebUI完全对等

### 2.5 前端

**Pipecat Voice UI Kit** (342 stars, React组件库)
- `@pipecat-ai/voice-ui-kit` — 现成UI组件（连接按钮、音频可视化、控制栏）
- `@pipecat-ai/client-react` — React hooks
- `@pipecat-ai/small-webrtc-transport` — WebRTC传输（无需Daily服务）
- 响应式设计：桌面/手机自适应
- Tailwind 4 样式，可完全自定义

---

## 三、系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          腾讯云服务器                                 │
│                                                                     │
│  ┌─────────────────┐         ┌──────────────────────────────────┐  │
│  │  Hermes Agent    │         │  Pipecat Voice Server            │  │
│  │  (Gateway模式)    │◄═══════│  bot.py                          │  │
│  │                  │  HTTP   │  ├─ STT: faster-whisper (base)   │  │
│  │  API Server      │  :8642  │  ├─ LLM: OpenAI → Hermes API    │  │
│  │  :8642/v1/*      │         │  ├─ TTS: Kokoro (本地ONNX)       │  │
│  │                  │         │  └─ Transport: SmallWebRTC        │  │
│  │  Gateway :8080   │         │         :7860                     │  │
│  │  ├─ 飞书通道      │         │                                  │  │
│  │  ├─ 微信通道      │         │  前端静态文件                      │  │
│  │  └─ API Server   │         │  voice.agentmj.vip               │  │
│  └─────────────────┘         └──────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         ▲                                           ▲
         │                                           │
    飞书/微信                                      WebRTC
    (现有通道)                                  (语音通道·新增)
         │                                           │
    ┌────┴────┐                              ┌───────┴───────┐
    │ 老李手机 │                              │ 浏览器/APP     │
    │ (文字)   │                              │ voice.agentmj │
    └─────────┘                              │ .vip          │
                                             │ (语音)        │
                                             └───────────────┘
```

---

## 四、文件结构（MVP）

```
hermes-voice-gateway/
├── README.md              # 本文件（研究文档）
├── bot.py                 # Pipecat bot主文件（STT→Hermes→TTS pipeline）
├── requirements.txt       # Python依赖
├── frontend/              # React前端（Voice UI Kit）
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx        # 主组件（使用ConsoleTemplate或自定义）
│   │   └── main.tsx
│   └── vite.config.ts
├── nginx/                 # Nginx配置（反向代理）
│   └── voice.conf
└── deploy.sh              # 一键部署脚本
```

---

## 五、核心代码设计

### 5.1 bot.py — Pipecat语音管道

```python
import os
import asyncio
from pipecat.services.openai import OpenAILLMService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.services.kokoro import KokoroTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.runner.run import main
from pipecat.runner.types import RunnerArguments
from pipecat.transports.base_transport import TransportParams

# ===== STT: 本地Whisper，免费 =====
stt = WhisperSTTService(
    settings=WhisperSTTService.Settings(
        model="base",
        language=Language.ZH,  # 中文识别
    ),
)

# ===== LLM: 连接Hermes Agent API =====
# 这是关键！不连接任何大模型，而是连接Hermes
llm = OpenAILLMService(
    api_key=os.getenv("HERMES_API_KEY", "change-me-local-dev"),
    base_url=os.getenv("HERMES_API_URL", "http://127.0.0.1:8642/v1"),
    model="hermes-agent",
)

# ===== TTS: 本地Kokoro，免费 =====
tts = KokoroTTSService(
    settings=KokoroTTSService.Settings(
        voice="af_heart",
        language=Language.ZH,  # 中文合成
    ),
)

async def run_bot(transport):
    """Transport无关的bot逻辑"""
    pipeline = Pipeline([
        transport.input(),   # 麦克风音频输入
        stt,                 # 语音转文字
        llm,                 # 文字转Hermes转回复文字
        tts,                 # 回复文字转语音
        transport.output(),  # 语音播放输出
    ])

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    await PipelineRunner().run(task)

async def bot(runner_args: RunnerArguments):
    """Pipecat Runner入口"""
    transport = SmallWebRTCTransport(
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
        webrtc_connection=runner_args.webrtc_connection,
    )
    await run_bot(transport)

if __name__ == "__main__":
    main()
```

### 5.2 前端 App.tsx

```tsx
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import '@pipecat-ai/voice-ui-kit/styles';

import { ConsoleTemplate, ThemeProvider } from '@pipecat-ai/voice-ui-kit';

export default function App() {
  return (
    <ThemeProvider>
      <div className="w-full h-dvh bg-background">
        <ConsoleTemplate
          transportType="smallwebrtc"
          connectParams={{
            webrtcUrl: '/api/offer',  // 指向Pipecat server
          }}
        />
      </div>
    </ThemeProvider>
  );
}
```

---

## 六、部署方案

### 6.1 服务器端（腾讯云）

```bash
# 1. 安装Pipecat + 依赖
pip install "pipecat-ai[whisper,kokoro,runner]"
pip install "pipecat-ai[openai]"

# 2. 确认Hermes API Server已启用
# ~/.hermes/.env 中：
# API_SERVER_ENABLED=true
# API_SERVER_KEY=your-secret-key

# 3. 启动Hermes Gateway
hermes gateway &

# 4. 启动Pipecat Voice Server
python bot.py -t webrtc --host 0.0.0.0 --port 7860
```

### 6.2 Nginx配置

```nginx
server {
    listen 443 ssl;
    server_name voice.agentmj.vip;

    # 前端静态文件
    location / {
        root /home/ubuntu/projects/hermes-voice-gateway/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # Pipecat WebRTC信令
    location /api/ {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

### 6.3 访问方式

- **浏览器**: https://voice.agentmj.vip → 点击连接 → 开始语音对话
- **手机浏览器**: 同上，响应式设计自动适配
- **后续扩展**: React Native SDK可打包为安卓APP

---

## 七、成本分析

| 组件 | 成本 | 备注 |
|------|------|------|
| Pipecat框架 | 免费 | BSD-2-Clause开源 |
| STT (faster-whisper) | 免费 | 本地CPU推理 |
| TTS (Kokoro) | 免费 | 本地ONNX推理 |
| LLM → Hermes → GLM/DeepSeek | 按现有API费用 | 不增加额外成本 |
| Voice UI Kit | 免费 | BSD-2-Clause开源 |
| WebRTC传输 | 免费 | SmallWebRTC，无需Daily/LiveKit |
| **总计新增成本** | **0元** | 全部使用免费组件 |

---

## 八、实施计划

| 阶段 | 内容 | 预计时间 |
|------|------|----------|
| Phase 1 | 服务器安装Pipecat + 依赖，写bot.py，本地测试CLI模式 | 2小时 |
| Phase 2 | 前端页面搭建（Voice UI Kit），WebRTC连接调试 | 3小时 |
| Phase 3 | Nginx配置 + 域名绑定，手机浏览器测试 | 1小时 |
| Phase 4 | 语音质量调优（中文识别率、TTS语音选择、延迟优化） | 2小时 |
| Phase 5 | 打包安卓APP（React Native，可选） | 后续 |

**MVP目标：** Phase 1-3 完成后，老李打开 voice.agentmj.vip 即可与墨凌语音对话。

---

## 九、关键依赖版本

| 组件 | 版本 | 说明 |
|------|------|------|
| Pipecat | v1.2.1 (2026-05-15) | 最新stable |
| faster-whisper | 内置 | Pipecat whisper extra |
| Kokoro TTS | kokoro-onnx>=0.5.0 | Pipecat kokoro extra |
| Voice UI Kit | v0.11.0 (2026-05-11) | React组件库 |
| Python | >=3.11 | Pipecat要求 |
| Node.js | v20+ | 前端构建 |

---

## 十、参考链接

| 资源 | URL |
|------|-----|
| Pipecat GitHub | https://github.com/pipecat-ai/pipecat |
| Pipecat 文档 | https://docs.pipecat.ai |
| Voice UI Kit | https://github.com/pipecat-ai/voice-ui-kit |
| Kokoro TTS | https://github.com/thewh1teagle/kokoro-onnx |
| Hermes API Server文档 | https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server |
| Pipecat Quickstart(客户端/服务器) | https://github.com/pipecat-ai/pipecat-quickstart-client-server |
| Pipecat Whisper STT | https://docs.pipecat.ai/api-reference/server/services/stt/whisper |
| Pipecat Kokoro TTS | https://docs.pipecat.ai/api-reference/server/services/tts/kokoro |
| Pipecat OpenAI LLM Service | https://docs.pipecat.ai/api-reference/server/services/llm/openai |
