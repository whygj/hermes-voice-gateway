"""
Hermes Voice Gateway — 通用语音交互中间件

架构：麦克风 → STT(faster-whisper) → LLM(OpenAI兼容接口) → TTS(Kokoro) → 扬声器
用途：让任何暴露 OpenAI 兼容 API 的 Agent 获得实时语音交互能力

用法：
  python bot.py                          # 默认配置
  python bot.py -t webrtc --port 7860    # WebRTC 模式
  python bot.py -t websocket --port 7860 # WebSocket 模式
"""

import os
import yaml
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
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments
from pipecat.transports.base_transport import TransportParams


def load_config(path="config.yaml"):
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), path)
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    # 默认配置
    return {
        "llm": {"base_url": "http://127.0.0.1:8642/v1", "api_key": "change-me-local-dev", "model": "hermes-agent"},
        "stt": {"provider": "whisper", "model": "base", "language": "zh"},
        "tts": {"provider": "kokoro", "voice": "af_heart", "language": "zh"},
    }


# 语言映射
LANG_MAP = {
    "zh": Language.ZH,
    "en": Language.EN,
    "ja": Language.JA,
    "ko": Language.KO,
    "fr": Language.FR,
    "de": Language.DE,
    "es": Language.ES,
}


def create_services(config):
    """根据配置创建 STT / LLM / TTS 服务"""

    cfg = config or {}
    stt_cfg = cfg.get("stt", {})
    llm_cfg = cfg.get("llm", {})
    tts_cfg = cfg.get("tts", {})

    # STT: 本地 faster-whisper
    stt = WhisperSTTService(
        settings=WhisperSTTService.Settings(
            model=stt_cfg.get("model", "base"),
            language=LANG_MAP.get(stt_cfg.get("language", "zh"), Language.ZH),
        ),
    )

    # LLM: 连接任意 OpenAI 兼容接口
    # 这是核心！改 base_url 就能对接不同的 Agent / 大模型
    llm = OpenAILLMService(
        api_key=llm_cfg.get("api_key", "change-me"),
        base_url=llm_cfg.get("base_url", "http://127.0.0.1:8642/v1"),
        model=llm_cfg.get("model", "hermes-agent"),
    )

    # TTS: 本地 Kokoro ONNX（首次运行自动下载模型）
    tts = KokoroTTSService(
        settings=KokoroTTSService.Settings(
            voice=tts_cfg.get("voice", "af_heart"),
            language=LANG_MAP.get(tts_cfg.get("language", "zh"), Language.ZH),
        ),
    )

    return stt, llm, tts


async def run_bot(transport, config=None):
    """Transport 无关的 bot 逻辑"""
    stt, llm, tts = create_services(config)

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


async def bot(runner_args: RunnerArguments):
    """Pipecat Runner 入口"""
    config = load_config()

    if isinstance(runner_args, SmallWebRTCRunnerArguments):
        transport = SmallWebRTCTransport(
            params=TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            ),
            webrtc_connection=runner_args.webrtc_connection,
        )
    else:
        # 其他 transport 类型可在此扩展
        raise ValueError(f"不支持的 transport 类型: {type(runner_args)}")

    await run_bot(transport, config)


if __name__ == "__main__":
    main()
