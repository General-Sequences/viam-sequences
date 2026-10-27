"""
The control loop against stand-ins: what it observes, which rows it plays when, how a new answer joins the old, the
gripper, the step that is refused, and how it stops. Each tick: read the robot, observe, take an answer that came, ask
for the next when it is due, play one row (or hold).

With `inline` the policy's calls run on the loop itself and `ticks` yields once a tick, so an act asked for on one tick
is answered by the next - the order of every row below is fixed.
"""
import asyncio

import numpy as np
import pytest
from fakes import FakeArm, FakeCamera, FakeGripper, FakePolicy

import sequence_ai
import settings
from loop import Loop


async def inline(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def make(attrs, arm, cameras, gripper, policy, **kw):
    s = settings.read({"policy": "pick-cube_user", "hz": 10, "arm": "arm", **attrs})
    return Loop(s, arm, cameras, gripper, connect=lambda model: policy, offload=inline, **kw)


def run(loop, ticks):
    """Run `loop` for `ticks` ticks, each sleep one turn of the event loop."""
    n = {"t": 0}

    async def sleep(_s):
        n["t"] += 1
        if n["t"] >= ticks:
            loop.request_stop()
        await asyncio.sleep(0)

    loop.sleep = sleep
    asyncio.run(loop.run())


def degrees(arm):
    return [[round(v, 6) for v in move] for move in arm.moves]


def rows(*joint_degrees, gripper=None):
    """An answer: one row a step, every joint at that row's degrees, in radians as a policy answers."""
    out = np.radians(np.repeat(np.asarray(joint_degrees, dtype=float)[:, None], 6, axis=1))
    return out if gripper is None else np.hstack([out, np.asarray(gripper, dtype=float)[:, None]])


def test_it_observes_each_camera_as_video_the_joints_in_radians_the_gripper_and_the_instruction():
    arm, policy = FakeArm([0, 90, -45, 0, 30, 0]), FakePolicy([rows(0, 0)])
    loop = make({"gripper": "hand", "cameras": {"front": "cam"}, "instruction": "stack the cubes"},
                arm, {"front": FakeCamera(48, 64, 200)}, FakeGripper(), policy)
    run(loop, 2)
    obs = policy.observed[0]
    assert set(obs) == {"front", "joints", "gripper", "instruction"}
    assert isinstance(obs["front"], sequence_ai.Video)
    frame = obs["front"].value
    assert frame.shape == (48, 64, 3) and frame.dtype == np.uint8 and abs(float(frame.mean()) - 200) < 3
    np.testing.assert_allclose(obs["joints"], np.radians([0, 90, -45, 0, 30, 0]), rtol=1e-6)
    assert obs["gripper"] == 0.0 and obs["instruction"] == "stack the cubes"


def test_a_policy_in_degrees_reads_and_answers_degrees():
    arm, policy = FakeArm([0, 10, 0, 0, 0, 0]), FakePolicy([np.full((2, 6), 12.0)])
    run(make({"joint_unit": "degrees"}, arm, {}, None, policy), 3)
    np.testing.assert_allclose(policy.observed[0]["joints"], [0, 10, 0, 0, 0, 0])
    assert degrees(arm) == [[12.0] * 6, [12.0] * 6]


def test_it_plays_each_row_in_degrees_asks_again_replan_at_rows_after_it_asked_and_joins_the_new_answer_where_it_is():
    arm, policy = FakeArm([0.0] * 6), FakePolicy([rows(0, 1, 2, 3, 4), rows(10, 11, 12, 13, 14)])
    loop = make({"replan_at": 3}, arm, {}, None, policy)
    run(loop, 7)
    # tick 0 asks and holds; ticks 1-3 play rows 0-2; tick 4, three rows after it asked, asks again and plays row 3;
    # tick 5 takes the new answer one row in - the robot played one row since it asked - and plays 11, then 12
    assert [m[0] for m in degrees(arm)] == [0, 1, 2, 3, 11, 12]
    status = loop.status()
    assert policy.acts == 2 and (status["acts"], status["holds"], status["steps"]) == (2, 1, 7)


def test_with_no_replan_at_it_asks_once_the_rows_run_out_and_holds_until_the_answer():
    arm, policy = FakeArm([0.0] * 6), FakePolicy([rows(1, 2), rows(5, 6)])
    loop = make({}, arm, {}, None, policy)
    run(loop, 6)
    assert [m[0] for m in degrees(arm)] == [1, 2, 5, 6]
    assert loop.status()["holds"] == 2


def test_valid_len_plays_no_row_past_it():
    arm, policy = FakeArm([0.0] * 6), FakePolicy([rows(1, 2, 3, 4), rows(7, 8, 9, 9)])
    run(make({"valid_len": 2}, arm, {}, None, policy), 6)
    assert [m[0] for m in degrees(arm)] == [1, 2, 7, 8]


def test_the_gripper_is_told_only_when_its_column_crosses_the_threshold():
    arm, policy, hand = FakeArm([0.0] * 6), FakePolicy([rows(0, 0, 0, 0, 0, gripper=[0.1, 0.2, 0.9, 0.8, 0.3])]), \
        FakeGripper()
    run(make({"gripper": "hand"}, arm, {}, hand, policy), 6)
    assert hand.calls == ["open", "grab", "open"]
    assert [o["gripper"] for o in policy.observed[1:6]] == [0.0, 0.0, 0.0, 1.0, 1.0]


@pytest.mark.parametrize("answer, key", [({"actions": rows(4, 5), "chunk_ms": 12.0}, None),
                                         ({"joint_targets": rows(4, 5), "actions": "not these"}, "joint_targets")])
def test_an_answer_that_is_a_dict_plays_its_actions_or_the_key_named(answer, key):
    arm = FakeArm([0.0] * 6)
    run(make({"action_key": key} if key else {}, arm, {}, None, FakePolicy([answer])), 3)
    assert [m[0] for m in degrees(arm)] == [4, 5]


def test_an_answer_with_no_actions_stops_it_naming_what_it_had():
    arm = FakeArm([0.0] * 6)
    loop = make({}, arm, {}, None, FakePolicy([{"joints_out": rows(1)}]))
    run(loop, 4)
    status = loop.status()
    assert status["state"] == "error" and "joints_out" in status["error"] and arm.moves == []


def test_a_row_moving_a_joint_past_max_joint_step_deg_is_refused_and_stops_the_arm():
    arm = FakeArm([0.0] * 6)
    loop = make({}, arm, {}, None, FakePolicy([np.radians([[0, 0, 0, 0, 0, 0], [45, 0, 0, 0, 0, 0]])]))
    run(loop, 5)
    status = loop.status()
    assert degrees(arm) == [[0.0] * 6] and status["state"] == "error" and arm.stops == 1
    assert "joint 0" in status["error"] and "45" in status["error"] and "max_joint_step_deg" in status["error"]


def test_a_policy_error_stops_it_and_says_so():
    class Failing(FakePolicy):
        def act(self):
            raise sequence_ai.SequencesError("the deployment is stopped")

    arm = FakeArm([0.0] * 6)
    loop = make({}, arm, {}, None, Failing())
    run(loop, 4)
    status = loop.status()
    assert status["state"] == "error" and "the deployment is stopped" in status["error"] and arm.stops == 1


def test_stop_cuts_through_an_act_that_waits_and_ends_the_episode():
    s = settings.read({"policy": "pick-cube_user", "hz": 20, "arm": "arm"})
    arm, policy = FakeArm([0.0] * 6), FakePolicy(hold=True)
    loop = Loop(s, arm, {}, None, connect=lambda model: policy)        # the policy's calls on threads, as on a robot

    async def main():
        loop.start()
        await asyncio.sleep(0.3)                                         # it asked, and the act waits
        assert loop.status()["state"] == "running" and policy.acts == 1 and not policy.interrupted.is_set()
        await asyncio.wait_for(loop.stop(), 5)

    asyncio.run(main())
    status = loop.status()
    assert status["state"] == "stopped" and "error" not in status and policy.ended == 1 and arm.stops == 1
    assert "last_act_s" not in status                                   # no act was answered: left out, not 0
    assert policy.interrupted.is_set() and arm.moves == []
