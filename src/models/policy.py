"""
The Viam service: a policy deployed on Sequences driving this machine's arm, its gripper and cameras.

In one sentence: viam-server builds it from the machine's config - validate_config names the arm, gripper and cameras
it drives, so they are up first - and a person runs it from the machine's page with do_command: {"command": "start"},
{"command": "stop"} to take the arm over with Viam's own controls, {"command": "status"}. The loop is loop.Loop; the
robot key comes from the module's environment (SEQUENCES_API_KEY), never from its attributes.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, Optional

from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.services.generic import Generic
from viam.utils import ValueTypes, struct_to_dict

import settings
from loop import Loop


def connect(model: str) -> Any:
    """The policy's connection: sequence_ai.connect - its key SEQUENCES_API_KEY, from the module's environment."""
    import sequence_ai

    return sequence_ai.connect(model)


class SequencesPolicy(Generic, EasyResource):
    MODEL = "general-sequences:sequences:policy"

    loop: Optional[Loop] = None

    @classmethod
    def new(cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]) -> "SequencesPolicy":
        self = super().new(config, dependencies)
        self.reconfigure(config, dependencies)
        return self

    @classmethod
    def validate_config(cls, config: ComponentConfig) -> tuple[Sequence[str], Sequence[str]]:
        return settings.read(struct_to_dict(config.attributes)).dependencies(), []

    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]) -> None:
        """A new loop on the new config; one that was running stops, and its successor starts once it has."""
        s = settings.read(struct_to_dict(config.attributes))
        arm = dependencies[Arm.get_resource_name(s.arm)]
        gripper = dependencies[Gripper.get_resource_name(s.gripper)] if s.gripper else None
        cameras = {key: dependencies[Camera.get_resource_name(name)] for key, name in s.cameras.items()}
        old, self.loop = self.loop, Loop(s, arm, cameras, gripper, connect=connect)
        if old is not None:
            running = old.state in ("starting", "running")
            old.request_stop()
            asyncio.ensure_future(self._hand_over(old, running))

    async def _hand_over(self, old: Loop, restart: bool) -> None:
        await old.close()
        if restart:
            self.loop.start()

    async def do_command(self, command: Mapping[str, ValueTypes], *, timeout: Optional[float] = None,
                         **kwargs: Any) -> Mapping[str, ValueTypes]:
        what = command.get("command")
        if what == "start":
            self.loop.start()
        elif what == "stop":
            await self.loop.stop()
        elif what != "status":
            raise ValueError(f"unknown command {what!r}: the commands are start, stop or status")
        return self.loop.status()

    async def close(self) -> None:
        if self.loop is not None:
            await self.loop.close()
