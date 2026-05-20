"""Edge TTS service for Pipecat — uses Microsoft Edge TTS (free, no API key)."""

import asyncio
import shutil
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

import edge_tts

SAMPLE_RATE = 24000
NUM_CHANNELS = 1


@dataclass
class EdgeTTSSettings(TTSSettings):
    pass


class EdgeTTSService(TTSService):
    Settings = EdgeTTSSettings
    _settings: Settings

    def __init__(self, *, voice: str = "zh-CN-XiaoxiaoNeural", settings: Settings | None = None, **kwargs):
        default_settings = self.Settings(model=None, voice=voice, language=None)

        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            push_start_frame=True,
            push_stop_frames=True,
            sample_rate=SAMPLE_RATE,
            settings=default_settings,
            **kwargs,
        )

        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise RuntimeError("ffmpeg not found — install it or add to PATH")

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"{self}: Generating TTS [{text}]")

        try:
            await self.start_tts_usage_metrics(text)

            voice = self._settings.voice or "zh-CN-XiaoxiaoNeural"

            # 1. Stream MP3 chunks from Edge TTS
            communicate = edge_tts.Communicate(text, voice)
            mp3_chunks = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_chunks.extend(chunk["data"])

            if not mp3_chunks:
                logger.warning(f"{self}: No audio received for [{text}]")
                return

            # 2. Convert MP3 → raw PCM (s16le, 24kHz, mono) via ffmpeg
            proc = await asyncio.create_subprocess_exec(
                self._ffmpeg, "-i", "pipe:0", "-f", "s16le", "-ar", str(SAMPLE_RATE),
                "-ac", str(NUM_CHANNELS), "-loglevel", "error", "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            pcm_data, stderr = await proc.communicate(input=bytes(mp3_chunks))

            if proc.returncode != 0:
                error_msg = stderr.decode(errors="replace").strip()
                yield ErrorFrame(error=f"ffmpeg failed (rc={proc.returncode}): {error_msg}")
                return

            if not pcm_data:
                logger.warning(f"{self}: ffmpeg produced no PCM for [{text}]")
                return

            # 3. Yield as a single TTSAudioRawFrame
            await self.stop_ttfb_metrics()
            yield TTSAudioRawFrame(
                audio=pcm_data,
                sample_rate=SAMPLE_RATE,
                num_channels=NUM_CHANNELS,
                context_id=context_id,
            )
        except Exception as e:
            logger.error(f"{self}: TTS error: {e}")
            yield ErrorFrame(error=f"Edge TTS error: {e}")
        finally:
            await self.stop_ttfb_metrics()
