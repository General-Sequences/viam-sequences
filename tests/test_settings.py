"""The service's attributes as a machine's config writes them, read once and checked, every refusal naming the
attribute and what it must be."""
import pytest

import settings


def test_the_least_a_machine_names_is_a_policy_its_rate_and_an_arm():
    s = settings.read({"policy": "pick-cube_user", "hz": 10, "arm": "arm-1"})
    assert (s.policy, s.hz, s.arm, s.cameras, s.gripper) == ("pick-cube_user", 10.0, "arm-1", {}, None)
    assert (s.joints_key, s.gripper_key, s.joint_unit, s.max_joint_step_deg) == ("joints", "gripper", "radians", 20.0)
    assert s.dependencies() == ["arm-1"]


def test_cameras_a_list_of_names_or_each_under_the_key_the_policy_reads_it_by():
    s = settings.read({"policy": "p", "hz": 15, "arm": "arm", "gripper": "hand",
                       "cameras": {"exterior_image": "cam-top", "wrist_image": "cam-wrist"}})
    assert s.cameras == {"exterior_image": "cam-top", "wrist_image": "cam-wrist"}
    assert s.dependencies() == ["arm", "hand", "cam-top", "cam-wrist"]
    assert settings.read({"policy": "p", "hz": 15, "arm": "arm", "cameras": ["front", "side"]}).cameras == \
        {"front": "front", "side": "side"}


def test_replan_at_and_valid_len_are_whole_steps_a_config_writes_as_numbers():
    s = settings.read({"policy": "p", "hz": 10, "arm": "a", "replan_at": 5.0, "valid_len": 10})
    assert (s.replan_at, s.valid_len) == (5, 10)


@pytest.mark.parametrize("attrs, said", [
    ({"hz": 10, "arm": "a"}, "policy"),
    ({"policy": "p", "arm": "a"}, "hz"),
    ({"policy": "p", "hz": 0, "arm": "a"}, "hz"),
    ({"policy": "p", "hz": "fast", "arm": "a"}, "hz"),
    ({"policy": "p", "hz": 10}, "arm"),
    ({"policy": "p", "hz": 10, "arm": "a", "replan_at": 2.5}, "replan_at"),
    ({"policy": "p", "hz": 10, "arm": "a", "joint_unit": "turns"}, "joint_unit"),
    ({"policy": "p", "hz": 10, "arm": "a", "cameras": {"joints": "cam"}}, "joints"),
    ({"policy": "p", "hz": 10, "arm": "a", "hzz": 5}, "hzz"),
])
def test_a_wrong_attribute_is_refused_naming_it(attrs, said):
    with pytest.raises(ValueError, match=said):
        settings.read(attrs)


@pytest.mark.parametrize("name", ["api_key", "key", "SEQUENCES_API_KEY"])
def test_the_robot_key_is_refused_in_the_attributes_which_anyone_who_sees_the_config_reads(name):
    with pytest.raises(ValueError, match="SEQUENCES_API_KEY"):
        settings.read({"policy": "p", "hz": 10, "arm": "a", name: "sk-robot"})


def test_key_file_is_an_absolute_path_on_the_machine():
    attrs = {"policy": "p", "hz": 10, "arm": "a"}
    assert settings.read({**attrs, "key_file": "/etc/sequences/robot.key"}).key_file == "/etc/sequences/robot.key"
    assert settings.read(attrs).key_file is None
    with pytest.raises(ValueError, match="key_file"):
        settings.read({**attrs, "key_file": "robot.key"})
