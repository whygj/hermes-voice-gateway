"""
Hermes Voice Gateway — 通用语音交互中间件

架构：麦克风 → SileroVAD → Whisper(STT) → LLMContext聚合 → OpenAI兼容LLM → Edge(TTS) → 扬声器
用途：让任何暴露 OpenAI 兼容 API 的 Agent 获得实时语音交互能力

用法：
  python bot.py                          # 默认 WebRTC, localhost:7860
  python bot.py -t webrtc --host 0.0.0.0 --port 7860  # 对外开放
"""

import os
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.run import main
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams


# ===== 配置区（环境变量 > 默认值）=====

HERMES_API_KEY = os.getenv("HERMES_API_KEY", "change-me-local-dev")
HERMES_API_URL = os.getenv("HERMES_API_URL", "http://127.0.0.1:8642/v1")

# STT: faster-whisper 本地，免费
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# TTS: Edge TTS (Microsoft, 免费, 支持中文)
EDGE_VOICE = os.getenv("EDGE_VOICE", "zh-CN-XiaoxiaoNeural")


transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    """Transport 无关的 pipeline 逻辑"""

    # STT: 语音 → 文字（本地 faster-whisper）
    stt = WhisperSTTService(
        settings=WhisperSTTService.Settings(
            model=WHISPER_MODEL,
            language=Language.ZH,
        ),
    )

    # LLM: 连接任意 OpenAI 兼容接口
    llm = OpenAILLMService(
        api_key=HERMES_API_KEY,
        base_url=HERMES_API_URL,
        settings=OpenAILLMService.Settings(
            model="hermes-agent",
            system_instruction="你叫墨凌（小凌），是一个AI助手。你在进行语音对话，请用简短自然的口语回答，不要用emoji、列表或其他无法朗读的格式。",
        ),
    )

    # TTS: 文字 → 语音（Edge TTS，免费，支持中文）
    from edge_tts_service import EdgeTTSService
    tts = EdgeTTSService(voice=EDGE_VOICE)

    # LLM 上下文 + 聚合器（VAD 检测用户说完 → 聚合成完整消息 → 触发 LLM）
    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # 组装 Pipeline
    pipeline = Pipeline([
        transport.input(),       # 麦克风音频输入
        stt,                     # 语音 → 文字
        user_aggregator,         # 聚合用户消息（等VAD检测说完）
        llm,                     # 文字 → Agent → 回复文字
        tts,                     # 回复文字 → 语音
        transport.output(),      # 语音播放输出
        assistant_aggregator,    # 聚合助手回复
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        # 启动对话
        context.add_message(
            {"role": "user", "content": "请用中文简短介绍自己，告诉用户你可以语音对话。"}
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Pipecat Runner 入口"""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    # 启动: python bot.py -t webrtc --host 0.0.0.0 --port 7860
    # 访问: http://localhost:7860/client
    main()
