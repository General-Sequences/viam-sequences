"""The service as viam-server runs it: the model its meta.json publishes, the dependencies its config names, and the
three commands - start, stop, status - a person sends from the machine's page."""
import asyncio
import json
import os
import pathlib

import pytest
from fakes import FakeArm, FakeCamera, FakeGripper, FakePolicy
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from viam.proto.app.robot import ComponentConfig
from viam.utils import dict_to_struct

from models import policy as module

ROOT = pathlib.Path(__file__).resolve().parents[1]
ATTRS = {"policy": "pick-cube_user", "hz": 20, "arm": "arm", "gripper": "hand", "cameras": {"front": "cam"}}


def config(attrs=ATTRS):
    return ComponentConfig(name="sequences", api="rdk:service:generic", model=str(module.SequencesPolicy.MODEL),
                           attributes=dict_to_struct(attrs))


def test_meta_json_publishes_the_model_the_code_registers_and_an_entrypoint_that_runs():
    meta = json.loads((ROOT / "meta.json").read_text())
    (model,) = meta["models"]
    assert (model["api"], model["model"]) == ("rdk:service:generic", str(module.SequencesPolicy.MODEL))
    assert meta["module_id"].split(":")[0] == model["model"].split(":")[0] and meta["visibility"] == "public"
    for script in (meta["entrypoint"], meta["first_run"]):
        assert (ROOT / script).is_file() and os.access(ROOT / script, os.X_OK), script


def test_validate_config_names_the_arm_the_gripper_and_the_cameras_and_refuses_a_bad_config():
    assert module.SequencesPolicy.validate_config(config()) == (["arm", "hand", "cam"], [])
    with pytest.raises(ValueError, match="hz"):
        module.SequencesPolicy.validate_config(config({**ATTRS, "hz": -1}))


def test_start_status_stop_from_the_machines_page(monkeypatch):
    arm, policy = FakeArm([0.0] * 6), FakePolicy([[[0.0] * 6 + [0.0]] * 4])
    monkeypatch.setattr(module, "connect", lambda model: policy)
    deps = {Arm.get_resource_name("arm"): arm, Gripper.get_resource_name("hand"): FakeGripper(),
            Camera.get_resource_name("cam"): FakeCamera()}

    async def main():
        service = module.SequencesPolicy.new(config(), deps)
        assert (await service.do_command({"command": "status"}))["state"] == "idle"
        assert (await service.do_command({"command": "start"}))["state"] in ("starting", "running")
        await asyncio.sleep(0.4)
        running = await service.do_command({"command": "status"})
        stopped = await service.do_command({"command": "stop"})
        with pytest.raises(ValueError, match="start, stop or status"):
            await service.do_command({"command": "go"})
        await service.close()
        return running, stopped

    running, stopped = asyncio.run(main())
    assert running["state"] == "running" and running["policy"] == "pick-cube_user" and running["steps"] > 2
    assert running["acts"] >= 1 and len(arm.moves) >= 1 and "front" in policy.observed[0]
    assert stopped["state"] == "stopped" and policy.ended == 1 and policy.closed
