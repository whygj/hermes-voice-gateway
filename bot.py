"""
Hermes Voice Gateway — 通用语音交互中间件

架构：麦克风 → faster-whisper(STT) → OpenAI兼容LLM → Kokoro(TTS) → 扬声器
用途：让任何暴露 OpenAI 兼容 API 的 Agent 获得实时语音交互能力

用法：
  python bot.py                          # 默认 WebRTC, localhost:7860
  python bot.py -t webrtc --host 0.0.0.0 --port 7860  # 对外开放
"""

import os
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.runner.run import main
from pipecat.runner.types import SmallWebRTCRunnerArguments
from pipecat.transports.base_transport import TransportParams


# ===== 配置区（环境变量 > 默认值）=====

HERMES_API_KEY = os.getenv("HERMES_API_KEY", "change-me-local-dev")
HERMES_API_URL = os.getenv("HERMES_API_URL", "http://127.0.0.1:8642/v1")

# STT: faster-whisper 本地，免费
# 模型选择：tiny(最快) / base(快+准) / medium(准+慢) / large(最准)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# TTS: Kokoro ONNX 本地，免费
# 语音：af_heart, af_bella, af_nicole, am_adam, bf_emma 等
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart")


async def run_bot(transport):
    """Transport 无关的 pipeline 逻辑"""
    # STT: 语音 → 文字（本地 faster-whisper）
    stt = WhisperSTTService(
        settings=WhisperSTTService.Settings(
            model=WHISPER_MODEL,
            language=Language.ZH,
        ),
    )

    # LLM: 连接任意 OpenAI 兼容接口
    # 核心：改 base_url 就能对接不同的 Agent / 大模型
    llm = OpenAILLMService(
        api_key=HERMES_API_KEY,
        base_url=HERMES_API_URL,
        model="hermes-agent",
    )

    # TTS: 文字 → 语音（本地 Kokoro ONNX）
    tts = KokoroTTSService(
        settings=KokoroTTSService.Settings(
            voice=KOKORO_VOICE,
            language=Language.ZH,
        ),
    )

    # 组装 Pipeline
    pipeline = Pipeline([
        transport.input(),   # 麦克风音频输入
        stt,                 # 语音 → 文字
        llm,                 # 文字 → Agent → 回复文字
        tts,                 # 回复文字 → 语音
        transport.output(),  # 语音播放输出
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True),
    )
    await PipelineRunner().run(task)


async def bot(runner_args: SmallWebRTCRunnerArguments):
    """Pipecat Runner 入口 — SmallWebRTC 模式"""
    transport = SmallWebRTCTransport(
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        webrtc_connection=runner_args.webrtc_connection,
    )
    await run_bot(transport)


if __name__ == "__main__":
    # 启动: python bot.py -t webrtc --host 0.0.0.0 --port 7860
    # 访问: http://localhost:7860/client
    main()
