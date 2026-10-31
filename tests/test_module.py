"""The service as viam-server runs it: the model its meta.json publishes, the dependencies its config names, and the
three commands - start, stop, status - a person sends from the machine's page."""
import asyncio
import inspect
import json
import os
import pathlib

import pytest
from fakes import FakeArm, FakeCamera, FakeGripper, FakePolicy, no_plan_yet
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
    monkeypatch.setattr(module, "connect", lambda model, **kw: policy)
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


def test_the_key_comes_from_key_file_on_the_machine_else_the_environment(tmp_path, monkeypatch):
    """viam-server writes a module's environment into the machine's logs when it starts it, the key with it: a key
    file read here never passes through the config or the logs."""
    import sequence_ai

    seen = {}
    monkeypatch.setattr(sequence_ai, "connect", lambda model, api_key=None: seen.update(model=model, key=api_key) or 1)
    key = tmp_path / "robot.key"
    key.write_text("sk-robot-123\n")
    module.connect("pick-cube_user", key_file=str(key))
    assert seen == {"model": "pick-cube_user", "key": "sk-robot-123"}
    module.connect("pick-cube_user")                       # SEQUENCES_API_KEY, as the SDK reads it
    assert seen["key"] is None
    for missing in (tmp_path / "missing.key", tmp_path / "empty.key"):
        if missing.name == "empty.key":
            missing.write_text("\n")
        with pytest.raises(Exception, match=str(missing)):
            module.connect("pick-cube_user", key_file=str(missing))


def test_through_the_planner_the_config_names_with_the_same_key(tmp_path, monkeypatch):
    """connect("<planner>", policy="<its policy>"), which the SDK takes. {the user 10-30 through third plan: "thorugh
    planner mean you do connect to that planner, and specify you are the pocliy of that planner whne you on the robot"}"""
    import sequence_ai

    inspect.signature(sequence_ai.connect).bind("site-planner_user", policy="pick-cube_user", api_key="sk-robot-123")
    seen = []
    monkeypatch.setattr(sequence_ai, "connect", lambda model, **kw: seen.append((model, kw)))
    key = tmp_path / "robot.key"
    key.write_text("sk-robot-123\n")
    module.connect("pick-cube_user", planner="site-planner_user")
    module.connect("pick-cube_user", key_file=str(key), planner="site-planner_user")
    module.connect("pick-cube_user", key_file=str(key))
    assert seen == [("site-planner_user", {"policy": "pick-cube_user"}),
                    ("site-planner_user", {"policy": "pick-cube_user", "api_key": "sk-robot-123"}),
                    ("pick-cube_user", {"api_key": "sk-robot-123"})]


def test_a_new_config_while_it_waits_for_a_plan_hands_over_to_a_loop_that_starts(monkeypatch):
    """Waiting for a plan it is running, as far as a new config goes: the machine's person sent start, and nothing since
    took it back."""
    arm, policy = FakeArm([0.0] * 6), FakePolicy([no_plan_yet()])
    asked = []
    monkeypatch.setattr(module, "connect", lambda model, **kw: asked.append((model, kw["planner"])) or policy)
    deps = {Arm.get_resource_name("arm"): arm, Gripper.get_resource_name("hand"): FakeGripper(),
            Camera.get_resource_name("cam"): FakeCamera()}
    attrs = {**ATTRS, "planner": "site-planner_user"}

    async def main():
        service = module.SequencesPolicy.new(config(attrs), deps)
        await service.do_command({"command": "start"})
        await asyncio.sleep(0.4)
        waiting = await service.do_command({"command": "status"})
        service.reconfigure(config({**attrs, "hz": 10}), deps)
        await asyncio.sleep(0.4)
        after = await service.do_command({"command": "status"})
        await service.close()
        return waiting, after

    waiting, after = asyncio.run(main())
    assert asked[0] == ("pick-cube_user", "site-planner_user") and len(asked) == 2
    assert waiting["state"] == "waiting_for_plan" and waiting["planner"] == "site-planner_user"
    assert (after["state"], after["hz"]) == ("waiting_for_plan", 10.0)
