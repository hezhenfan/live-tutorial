# Copyright 2023 LiveKit, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import logging
import os
import uuid
import wave
from contextlib import suppress
from dataclasses import dataclass
from typing import List
from urllib.parse import urlencode
import cv2

import aiohttp
import numpy as np
from livekit import rtc
from livekit.agents import stt
from livekit.agents.utils import AudioBuffer, merge_frames

from .audio2secc_deploy.inference_with_new_video import inference

logger = logging.getLogger('stt')
logging.basicConfig(encoding='utf-8')


@dataclass
class STTOptions:
    language: str
    detect_language: bool
    interim_results: bool
    punctuate: bool
    model: str
    smart_format: bool
    endpointing: int | None


class STT:
    def __init__(self):
        super().__init__()

    def stream(
        self
    ) -> "SpeechStream":
        return SpeechStream()


class SpeechStream:
    temp_wav = '/home/ecs-user/code/ai-livetutorial/ai-avatar/plugins/wav/'
    temp_avi = '/home/ecs-user/code/ai-livetutorial/ai-avatar/plugins/avi/'

    def __init__(self) -> None:
        super().__init__()

        self._session = aiohttp.ClientSession()
        self._queue = asyncio.Queue[rtc.AudioFrame | str]()
        self.output_queue = asyncio.Queue[rtc.VideoFrame | str]()
        self._wav_queue = asyncio.Queue[str]()
        self._avi_queue = asyncio.Queue[str]()
        self._event_queue = asyncio.Queue[stt.SpeechEvent | None]()
        self._closed = False
        self._main_task = asyncio.create_task(self._run())

        # keep a list of final transcripts to combine them inside the END_OF_SPEECH event
        self._final_events: List[stt.SpeechEvent] = []

        def log_exception(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logging.error(f"deepgram task failed: {task.exception()}")

        self._main_task.add_done_callback(log_exception)

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        if self._closed:
            raise ValueError("cannot push frame to closed stream")

        self._queue.put_nowait(frame)

    async def aclose(self, wait: bool = True) -> None:
        self._closed = True
        self._queue.put_nowait('')

        if not wait:
            self._main_task.cancel()

        with suppress(asyncio.CancelledError):
            await self._main_task

        await self._session.close()

    async def _run(self) -> None:
        """
        This method can throw ws errors, these are handled inside the _run method
        """

        closing_ws = False

        async def send_task():
            nonlocal closing_ws
            # forward inputs to deepgram
            # if we receive a close message, signal it to deepgram and break.
            # the recv task will then make sure to process the remaining audio and stop
            all_bytes=b''
            while True:
                data = await self._queue.get()
                self._queue.task_done()

                if isinstance(data, rtc.AudioFrame):
                    # TODO(theomonnom): The remix_and_resample method is low quality
                    # and should be replaced with a continuous resampling
                    frame = data.remix_and_resample(16000, 1)
                    all_bytes += frame.data.tobytes()
                    if len(all_bytes) > 500_000:
                        wav_file = self.temp_wav + f'{uuid.uuid4().hex}.wav'
                        with wave.open(wav_file, 'wb') as f:
                            f.setnchannels(1)
                            f.setsampwidth(2)
                            f.setframerate(16000)
                            f.writeframes(all_bytes)
                        self._wav_queue.put_nowait(wav_file)
                        all_bytes = b''
                        logger.info(f'存下一个音频文件')

        async def recv_task():
            nonlocal closing_ws
            while True:
                data = await self._wav_queue.get()
                logger.info(f'取一个wav音频文件')
                self._wav_queue.task_done()
                if isinstance(data, str):
                    video_file = self.temp_avi + f'{uuid.uuid4().hex}.avi'
                    try:
                        logger.info(f'开始推理')
                        await asyncio.get_event_loop().run_in_executor(None, inference, data, video_file)
                        logger.info(f'推理结束')
                        self._avi_queue.put_nowait(video_file)
                    except Exception as e:
                        logging.error(f"failed to process audio: {e}")

        async def video_frame_task():
            while True:
                data = await self._avi_queue.get()
                logger.info(f'取一个avi视频文件')
                self._avi_queue.task_done()
                if isinstance(data, str):
                    cap = cv2.VideoCapture(data)
                    while True:
                        ret, rgb_frame = cap.read()
                        if not ret:
                            break
                        height, width, _ = rgb_frame.shape
                        rgba_array = np.zeros((height, width, 4), dtype=np.uint8)
                        rgba_array[:, :, :3] = rgb_frame
                        rgba_array[:, :, 3] = 255
                        frame = rtc.VideoFrame(height, width, rtc.VideoBufferType.BGRA, rgba_array.tobytes())
                        self.output_queue.put_nowait(frame)
                    cap.release()

        await asyncio.gather(send_task(), recv_task(), video_frame_task())

    async def __anext__(self) -> stt.SpeechEvent:
        evt = await self._event_queue.get()
        if evt is None:
            raise StopAsyncIteration

        return evt
