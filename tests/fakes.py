"""
Stand-ins for what the module drives: an arm in degrees, a camera that answers JPEG frames, a gripper that opens and
grabs, and a policy handle with sequence_ai.Policy's calls - each recording what it was asked, so a test reads back
what the module did to the robot and sent to the policy.
"""
from __future__ import annotations

import io
import threading
from typing import Any

import numpy as np
from PIL import Image
from viam.media.video import CameraMimeType, NamedImage
from viam.proto.common import ResponseMetadata
from viam.proto.component.arm import JointPositions

import sequence_ai


class FakeArm:
    def __init__(self, degrees: list[float]) -> None:
        self.degrees = list(degrees)
        self.moves: list[list[float]] = []
        self.stops = 0

    async def get_joint_positions(self, **kwargs: Any) -> JointPositions:
        return JointPositions(values=self.degrees)

    async def move_to_joint_positions(self, positions: JointPositions, **kwargs: Any) -> None:
        self.degrees = list(positions.values)
        self.moves.append(list(positions.values))

    async def stop(self, **kwargs: Any) -> None:
        self.stops += 1


def jpeg(height: int, width: int, value: int) -> bytes:
    out = io.BytesIO()
    Image.fromarray(np.full((height, width, 3), value, dtype=np.uint8)).save(out, format="JPEG")
    return out.getvalue()


class FakeCamera:
    def __init__(self, height: int = 48, width: int = 64, value: int = 128) -> None:
        self.frame = jpeg(height, width, value)
        self.reads = 0

    async def get_images(self, **kwargs: Any) -> tuple[list[NamedImage], ResponseMetadata]:
        self.reads += 1
        return [NamedImage("color", self.frame, CameraMimeType.JPEG)], ResponseMetadata()


class FakeGripper:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def open(self, **kwargs: Any) -> None:
        self.calls.append("open")

    async def grab(self, **kwargs: Any) -> bool:
        self.calls.append("grab")
        return True

    async def stop(self, **kwargs: Any) -> None:
        self.calls.append("stop")


class FakePolicy:
    """sequence_ai.Policy's calls: `answers` handed out by act() in turn (the last again once they run out); with
    `hold`, act() waits until interrupt() and raises sequence_ai.Interrupted, as a real act waiting on a starting worker
    does."""

    def __init__(self, answers: list[Any] | None = None, *, hold: bool = False) -> None:
        self.answers = list(answers or [])
        self.observed: list[dict] = []
        self.acts = 0
        self.ended = 0
        self.closed = False
        self.hold = hold
        self.interrupted = threading.Event()

    def observe(self, inputs: Any, *, episode_id: str | None = None) -> int:
        self.observed.append(inputs)
        return len(self.observed) - 1

    def act(self) -> Any:
        self.acts += 1
        if self.hold:
            self.interrupted.wait(10)
            raise sequence_ai.Interrupted("interrupted")
        return self.answers[min(self.acts, len(self.answers)) - 1]

    def interrupt(self) -> None:
        self.interrupted.set()

    def end_episode(self, episode_id: str | None = None) -> None:
        self.ended += 1

    def close(self) -> None:
        self.closed = True
