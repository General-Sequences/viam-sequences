"""
The service's attributes, as a machine's config writes them: read once, checked, every refusal naming the attribute and
what it must be - viam-server shows it on the machine's page before anything runs.

    {"policy": "pick-cube", "hz": 15, "arm": "arm-1", "gripper": "gripper-1",
     "cameras": {"exterior_image": "cam-top", "wrist_image": "cam-wrist"}}

What the policy reads goes under the keys its observe function reads them by: each camera under its key (a list of
camera names puts each under its own name), the arm's joints under `joints_key`, the gripper under `gripper_key`, an
`instruction` under `instruction_key`. The robot key is never an attribute: everyone who can see the machine's config
reads its attributes, so it goes in the module's environment, SEQUENCES_API_KEY.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

UNITS = ("radians", "degrees")
_KEY_ATTRS = ("api_key", "key", "SEQUENCES_API_KEY")
_KNOWN = ("policy", "hz", "arm", "gripper", "cameras", "joints_key", "gripper_key", "instruction", "instruction_key",
          "action_key", "replan_at", "valid_len", "joint_unit", "gripper_threshold", "max_joint_step_deg")


@dataclass(frozen=True)
class Settings:
    policy: str
    hz: float
    arm: str
    cameras: dict[str, str] = field(default_factory=dict)   # the key the policy reads a frame by -> the camera
    gripper: Optional[str] = None
    joints_key: str = "joints"
    gripper_key: str = "gripper"
    instruction: Optional[str] = None
    instruction_key: str = "instruction"
    action_key: Optional[str] = None          # where the rows are in an answer that is a dict: "actions" when unset
    replan_at: Optional[int] = None           # rows played after an act is sent before the next is: all of them unset
    valid_len: Optional[int] = None           # rows of an answer that are played: all of them unset
    joint_unit: str = "radians"               # the policy's: the arm reads and takes degrees
    gripper_threshold: float = 0.5            # the gripper column at or above it: closed
    max_joint_step_deg: float = 20.0          # a row moving a joint further in one step is refused; 0: no limit

    def dependencies(self) -> list[str]:
        """The resources it drives, as viam-server is told them: the arm, the gripper, each camera once."""
        cameras = list(dict.fromkeys(self.cameras.values()))
        return [self.arm, *([self.gripper] if self.gripper else []), *cameras]


def _name(attrs: Mapping[str, Any], key: str, *, required: bool = False, default: Optional[str] = None) -> Optional[str]:
    value = attrs.get(key, default)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string" + (" (it is required)" if required else ""))
    return value.strip()


def _number(attrs: Mapping[str, Any], key: str, default: Optional[float], *, low: float, strict: bool) -> Optional[float]:
    value = attrs.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < low or (strict and value == low):
        raise ValueError(f"{key} must be a number {'above' if strict else 'at least'} {low:g}, not {value!r}")
    return float(value)


def _steps(attrs: Mapping[str, Any], key: str) -> Optional[int]:
    value = attrs.get(key)
    if value is None:
        return None
    # a config's numbers arrive as floats (a protobuf Struct holds doubles): 5.0 is the 5 a person wrote
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or value < 1:
        raise ValueError(f"{key} must be a whole number of steps, 1 or more, not {value!r}")
    return int(value)


def _cameras(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) and v for v in value):
        return {v: v for v in value}
    if isinstance(value, Mapping) and all(isinstance(k, str) and k and isinstance(v, str) and v
                                          for k, v in value.items()):
        return dict(value)
    raise ValueError("cameras must be a list of camera names, or a map from the key the policy reads a frame by to "
                     "the camera's name")


def read(attrs: Mapping[str, Any]) -> Settings:
    """The attributes as Settings; ValueError naming the first one that is wrong."""
    for key in _KEY_ATTRS:
        if key in attrs:
            raise ValueError(f"{key}: the robot key goes in the module's environment, SEQUENCES_API_KEY - never in its "
                             "attributes, which everyone who can see this machine's config reads")
    unknown = sorted(set(attrs) - set(_KNOWN))
    if unknown:
        raise ValueError(f"unknown attribute {unknown[0]!r}; the attributes are {', '.join(_KNOWN)}")
    unit = attrs.get("joint_unit", "radians")
    if unit not in UNITS:
        raise ValueError(f"joint_unit must be one of {', '.join(UNITS)}, not {unit!r}")
    s = Settings(policy=_name(attrs, "policy", required=True), hz=_number(attrs, "hz", None, low=0, strict=True),
                 arm=_name(attrs, "arm", required=True), cameras=_cameras(attrs.get("cameras")),
                 gripper=_name(attrs, "gripper"), joints_key=_name(attrs, "joints_key", default="joints"),
                 gripper_key=_name(attrs, "gripper_key", default="gripper"), instruction=_name(attrs, "instruction"),
                 instruction_key=_name(attrs, "instruction_key", default="instruction"),
                 action_key=_name(attrs, "action_key"), replan_at=_steps(attrs, "replan_at"),
                 valid_len=_steps(attrs, "valid_len"), joint_unit=unit,
                 gripper_threshold=_number(attrs, "gripper_threshold", 0.5, low=float("-inf"), strict=False),
                 max_joint_step_deg=_number(attrs, "max_joint_step_deg", 20.0, low=0, strict=False))
    if s.hz is None:
        raise ValueError("hz must be a number above 0 (it is required): the steps a second the arm plays")
    keys = [*s.cameras, s.joints_key] + ([s.gripper_key] if s.gripper else []) + \
        ([s.instruction_key] if s.instruction else [])
    taken = sorted({k for k in keys if keys.count(k) > 1})
    if taken:
        raise ValueError(f"the observation key {taken[0]!r} is given twice: each camera, the joints, the gripper and "
                         "the instruction go under keys of their own")
    return s
