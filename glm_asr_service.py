"""GLM ASR service for Pipecat — uses Zhipu GLM-ASR-2512 cloud API."""

import asyncio
import io
import os
import time
import wave
from collections.abc import AsyncGenerator

import aiohttp
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService


class GLMASRSettings(STTSettings):
    """Settings for GLM ASR service (language auto-detected by the API)."""
    pass


class GLMASRService(STTService):
    """Pipecat STT service backed by Zhipu GLM-ASR-2512 cloud API.

    Receives raw PCM bytes from WebRTC (16 kHz, 16-bit, mono), converts them
    to WAV via the ``wave`` stdlib module, then POSTs to the Zhipu transcription
    endpoint and yields a ``TranscriptionFrame``.
    """

    Settings = GLMASRSettings
    _settings: Settings

    _API_URL = "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions"
    _MODEL = "glm-asr-2512"

    # PCM params expected by Pipecat WebRTC transport
    _SAMPLE_RATE = 16000
    _SAMPLE_WIDTH = 2   # 16-bit
    _NUM_CHANNELS = 1

    def __init__(
        self,
        *,
        api_key: str | None = None,
        settings: Settings | None = None,
        **kwargs,
    ):
        default_settings = self.Settings(model=self._MODEL, language=None)
        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            settings=default_settings,
            **kwargs,
        )

        self._api_key = api_key or os.getenv("GLM_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "GLM ASR API key is required — pass api_key= or set GLM_API_KEY env var"
            )

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000, sample_width: int = 2,
                    channels: int = 1) -> bytes:
        """Convert raw PCM bytes to WAV format using the stdlib wave module."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Transcribe raw PCM audio via GLM-ASR-2512 cloud API."""
        if not audio:
            return

        try:
            # 1. Wrap raw PCM into a WAV (in-memory, no ffmpeg needed)
            wav_bytes = self._pcm_to_wav(
                audio,
                sample_rate=self._SAMPLE_RATE,
                sample_width=self._SAMPLE_WIDTH,
                channels=self._NUM_CHANNELS,
            )

            if not wav_bytes:
                logger.warning(f"{self}: produced empty WAV from {len(audio)} PCM bytes")
                return

            # 2. POST to Zhipu ASR API
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("model", self._MODEL)
                form.add_field(
                    "file",
                    wav_bytes,
                    filename="audio.wav",
                    content_type="audio/wav",
                )
                form.add_field("stream", "false")

                headers = {"Authorization": f"Bearer {self._api_key}"}

                async with session.post(
                    self._API_URL,
                    data=form,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"{self}: GLM ASR HTTP {resp.status}: {body}")
                        yield ErrorFrame(error=f"GLM ASR HTTP {resp.status}: {body[:200]}")
                        return

                    data = await resp.json()

            text = data.get("text", "").strip()
            if not text:
                logger.debug(f"{self}: GLM ASR returned empty transcription")
                return

            logger.info(f"{self}: GLM ASR transcription: [{text}]")
            yield TranscriptionFrame(
                text=text,
                user_id=self._user_id,
                timestamp=time.isoformat(sep=" ", timespec="milliseconds"),
            )

        except Exception as e:
            logger.error(f"{self}: GLM ASR error: {e}")
            yield ErrorFrame(error=f"GLM ASR error: {e}")
