"""
The control loop: at the machine's rate (`hz`), read the robot - each camera's frame, the arm's joints, the gripper as
it was last told - and hand it to the policy (`observe`); ask for an answer (`act`) when one is due, on a thread of its
own, so the arm keeps playing while it is asked; play one row of the answer a step - the joints to
move_to_joint_positions, the gripper when its column crosses the threshold - or hold while there is no row to play.

An answer is due once `replan_at` rows have been played since the last one was asked for - every row of it when
replan_at is unset, as a policy's action_chunk_replan_at says - and the answer, when it comes, joins where the robot
is: as many rows in as were played since it was asked for. A robot that played none (it held) starts at the first.

WHY each call to the policy runs on a thread: its first observe waits out a worker that is starting, and an act waits
for its answer - the module's own loop has to stay free for `stop`, which interrupts either.
"""
from __future__ import annotations

import asyncio
import io
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Optional

import numpy as np
from PIL import Image
from viam.media.video import CameraMimeType
from viam.proto.component.arm import JointPositions

import sequence_ai
from settings import Settings

_RGBA_HEADER = 12          # a Viam RGBA frame's header: its signature, width and height, 4 bytes each


class Refused(Exception):
    """What stops the loop on its own, in the words the machine's page shows."""


class Loop:
    def __init__(self, settings: Settings, arm: Any, cameras: Mapping[str, Any], gripper: Any = None, *,
                 connect: Callable[[str], Any], offload: Callable[..., Awaitable[Any]] = asyncio.to_thread,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.settings, self.arm, self.cameras, self.gripper = settings, arm, dict(cameras), gripper
        self.connect, self.offload, self.sleep, self.clock = connect, offload, sleep, clock
        self.policy: Any = None
        self.state, self.error = "idle", None
        self.steps = self.acts = self.rows_played = self.holds = 0
        self.last_act_s: Optional[float] = None
        self._stopping = threading.Event()
        self._task: Optional[asyncio.Task] = None
        self._closed_hand: Optional[bool] = None       # what the gripper was last told; None before it was told
        self._hand_task: Optional[asyncio.Future] = None

    # ── what the service calls ──────────────────────────────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Run the loop as a task of the module's event loop, if it is not running."""
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self.error, self.steps, self.acts, self.rows_played, self.holds = None, 0, 0, 0, 0
        self.state = "starting"                     # said at once: the page that sent start reads it next
        self._task = asyncio.ensure_future(self.run())

    def request_stop(self) -> None:
        """Stop at the next step, cutting through a call to the policy that waits. Thread-safe."""
        self._stopping.set()
        if self.policy is not None:
            self.policy.interrupt()

    async def stop(self) -> None:
        self.request_stop()
        if self._task is not None:
            await self._task

    async def close(self) -> None:
        await self.stop()
        if self.policy is not None:
            policy, self.policy = self.policy, None
            await self.offload(policy.close)

    def status(self) -> dict:
        """What the machine's page shows. A value not known yet - no act answered, no error - is left out: a Viam
        command's answer carries a null as 0, which would read as an act of 0 s."""
        s = self.settings
        out = {"state": self.state, "policy": s.policy, "hz": s.hz, "steps": self.steps, "acts": self.acts,
               "rows_played": self.rows_played, "holds": self.holds,
               "last_act_s": None if self.last_act_s is None else round(self.last_act_s, 3), "error": self.error}
        return {k: v for k, v in out.items() if v is not None}

    # ── the loop ────────────────────────────────────────────────────────────────────────────────────────────────────
    async def run(self) -> None:
        self.state = "starting"
        pending: Optional[asyncio.Future] = None
        try:
            if self.policy is None:
                self.policy = await self.offload(self.connect, self.settings.policy)
            period = 1.0 / self.settings.hz
            rows: Optional[np.ndarray] = None
            row = since_ask = 0
            asked_at = 0.0
            while not self._stopping.is_set():
                began = self.clock()
                degrees = list((await self.arm.get_joint_positions()).values)
                await self.offload(self.policy.observe, await self._observation(degrees))
                if self._stopping.is_set():
                    break
                self.state = "running"
                if pending is not None and pending.done():
                    rows, pending = self._rows(pending.result()), None
                    self.acts += 1
                    self.last_act_s = self.clock() - asked_at
                    row = since_ask                 # joins where the robot is: the rows it played since asking skipped
                if pending is None and (rows is None or since_ask >= min(self.settings.replan_at or len(rows),
                                                                          len(rows))):
                    asked_at, since_ask = self.clock(), 0
                    pending = asyncio.ensure_future(self.offload(self.policy.act))
                if rows is not None and row < len(rows):
                    await self._play(rows[row], degrees)
                    row, since_ask, self.rows_played = row + 1, since_ask + 1, self.rows_played + 1
                else:
                    self.holds += 1                 # no row to play: the arm stays where it is
                self.steps += 1
                await self.sleep(max(0.0, period - (self.clock() - began)))
            self.state = "stopped"
        except sequence_ai.Interrupted:             # a BaseException: stop() cut through a call that waited
            self.state = "stopped"
        except Exception as exc:  # noqa: BLE001 - whatever stopped it is said on the machine's page
            self.state = "error"
            self.error = str(exc) if isinstance(exc, Refused) else f"{type(exc).__name__}: {exc}"
        finally:
            await self._wind_down(pending)

    async def _wind_down(self, pending: Optional[asyncio.Future]) -> None:
        """The arm stopped and the episode ended, whatever ended the loop; an act still out is interrupted."""
        self._stopping.set()
        if pending is not None and not pending.done():
            self.policy.interrupt()
            pending.add_done_callback(lambda f: f.cancelled() or f.exception())
        elif pending is not None and not pending.cancelled():
            pending.exception()                      # taken, so it is not reported as never retrieved
        if self.policy is not None:
            try:
                await self.offload(self.policy.end_episode)
            except (Exception, sequence_ai.Interrupted):  # noqa: BLE001 - the next start opens a new episode anyway
                pass
        try:
            await self.arm.stop()
        except Exception:  # noqa: BLE001 - an arm that cannot be told to stop has stopped being driven all the same
            pass

    # ── one step ────────────────────────────────────────────────────────────────────────────────────────────────────
    async def _observation(self, degrees: list[float]) -> dict:
        s = self.settings
        obs: dict[str, Any] = {key: sequence_ai.Video(await self._frame(key)) for key in self.cameras}
        joints = np.asarray(degrees, dtype=np.float32)
        obs[s.joints_key] = np.radians(joints) if s.joint_unit == "radians" else joints
        if self.gripper is not None:
            obs[s.gripper_key] = 1.0 if self._closed_hand else 0.0
        if s.instruction:
            obs[s.instruction_key] = s.instruction
        return obs

    async def _frame(self, key: str) -> np.ndarray:
        """The camera's first image as HxWx3 uint8: a JPEG or PNG decoded, a Viam RGBA frame without its alpha."""
        images, _ = await self.cameras[key].get_images()
        if not images:
            raise Refused(f"camera {self.settings.cameras[key]!r} answered no image")
        image = images[0]
        if image.mime_type == CameraMimeType.VIAM_RGBA and image.width and image.height:
            pixels = np.frombuffer(image.data, dtype=np.uint8, offset=_RGBA_HEADER)
            return pixels.reshape(image.height, image.width, 4)[:, :, :3].copy()
        with Image.open(io.BytesIO(image.data)) as decoded:
            return np.asarray(decoded.convert("RGB"), dtype=np.uint8)

    def _rows(self, answer: Any) -> np.ndarray:
        """The answer's rows - one a step, the arm's joints then the gripper - cut to valid_len."""
        s = self.settings
        if isinstance(answer, Mapping):
            key = s.action_key or "actions"
            if key not in answer:
                held = ", ".join(sorted(map(str, answer))) or "nothing"
                raise Refused(f"the policy's answer has no {key!r} (it holds {held}): set action_key to the key its "
                              "rows are under")
            answer = answer[key]
        rows = np.asarray(answer, dtype=np.float64)
        if rows.ndim == 1:
            rows = rows[None, :]
        if rows.ndim != 2 or not rows.shape[0]:
            raise Refused(f"the policy answered an array of shape {rows.shape}, where rows - one a step, the arm's "
                          "joints then the gripper - are played")
        return rows[: s.valid_len] if s.valid_len else rows

    async def _play(self, values: np.ndarray, degrees: list[float]) -> None:
        s, n = self.settings, len(degrees)
        if len(values) < n:
            raise Refused(f"the policy's rows hold {len(values)} values and the arm has {n} joints")
        target = np.degrees(values[:n]) if s.joint_unit == "radians" else np.asarray(values[:n], dtype=np.float64)
        if s.max_joint_step_deg > 0:
            moved = np.abs(target - np.asarray(degrees, dtype=np.float64))
            joint = int(np.argmax(moved))
            if moved[joint] > s.max_joint_step_deg:
                raise Refused(f"step {self.steps}: joint {joint} would move {moved[joint]:.1f} degrees in one step, "
                              f"past max_joint_step_deg={s.max_joint_step_deg:g}; the arm is stopped")
        await self.arm.move_to_joint_positions(JointPositions(values=[float(v) for v in target]))
        if self.gripper is not None and len(values) > n:
            closed = bool(values[n] >= s.gripper_threshold)
            if closed != self._closed_hand and (self._hand_task is None or self._hand_task.done()):
                self._closed_hand = closed
                self._hand_task = asyncio.ensure_future(self.gripper.grab() if closed else self.gripper.open())
