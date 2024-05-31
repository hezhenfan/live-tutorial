import asyncio
import json
import logging
import time

from dotenv import load_dotenv
load_dotenv()

from livekit import agents, rtc
from livekit.agents import (
    JobContext,
    JobRequest,
    WorkerOptions,
    cli,
)

import os
import sys
sys.path.append(os.getcwd())
from plugins.avatar import STT
from state_manager import StateManager


PROMPT = "You are KITT, a friendly voice assistant powered by LiveKit.  \
          Conversation should be personable, and be sure to ask follow up questions. \
          If your response is a question, please append a question mark symbol to the end of it.\
          Don't respond with more than a few sentences."
INTRO = "Hello, I am KITT, a friendly voice assistant powered by LiveKit Agents. \
        You can find my source code in the top right of this screen if you're curious how I work. \
        Feel free to ask me anything — I'm here to help! Just start talking or type in the chat."
SIP_INTRO = "Hello, I am KITT, a friendly voice assistant powered by LiveKit Agents. \
             Feel free to ask me anything — I'm here to help! Just start talking."
SIP_ZH = "你好."


async def entrypoint(job: JobContext):
    # LiveKit Entities
    source = rtc.AudioSource(24000, 1)
    video_source = rtc.VideoSource(512, 512)
    track = rtc.LocalAudioTrack.create_audio_track("agent-mic", source)
    video_track = rtc.LocalVideoTrack.create_video_track("agent-cam", video_source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_MICROPHONE
    options_video = rtc.TrackPublishOptions()
    options_video.source = rtc.TrackSource.SOURCE_CAMERA

    # Plugins
    stt = STT()
    stt_stream = stt.stream()

    # Agent state
    state = StateManager(job.room, PROMPT)
    inference_task: asyncio.Task | None = None
    current_transcription = ""

    audio_stream_future = asyncio.Future[rtc.AudioStream]()

    def on_track_subscribed(track: rtc.Track, *_):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream_future.set_result(rtc.AudioStream(track))

    for participant in job.room.participants.values():
        for track_pub in participant.tracks.values():
            # This track is not yet subscribed, when it is subscribed it will
            # call the on_track_subscribed callback
            if track_pub.track is None:
                continue
            audio_stream_future.set_result(rtc.AudioStream(track_pub.track))

    job.room.on("track_subscribed", on_track_subscribed)

    # Wait for user audio
    audio_stream = await audio_stream_future

    # Publish agent mic after waiting for user audio (simple way to avoid subscribing to self)
    await job.room.local_participant.publish_track(track, options)
    await job.room.local_participant.publish_track(video_track, options_video)

    async def audio_stream_task():
        while 1:
            logging.getLogger().info(f'1')
        async for audio_frame_event in audio_stream:
            logging.getLogger().info(f'开始捕获音频帧: {type(audio_frame_event.frame)}')
            stt_stream.push_frame(audio_frame_event.frame)

    async def video_capture_task():
        while True:
            video_frame = await stt_stream.output_queue.get()
            video_source.capture_frame(video_frame)
            time.sleep(0.04)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(audio_stream_task())
            tg.create_task(video_capture_task())
    except BaseExceptionGroup as e:
        for exc in e.exceptions:
            print("Exception: ", exc)
    except Exception as e:
        print("Exception: ", e)


async def request_fnc(req: JobRequest) -> None:
    await req.accept(entrypoint, auto_subscribe=agents.AutoSubscribe.SUBSCRIBE_ALL)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(request_fnc=request_fnc))
