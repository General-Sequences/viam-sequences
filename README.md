# Sequences for Viam

Drive your arm with a policy you deployed on [Sequences](https://generalsequences.com/docs/). This module reads your
machine's cameras and joints, hands them to your policy, and plays the joint targets it answers on your arm and
gripper, at the rate you set. To take the arm back, send `stop` from the machine's page and use Viam's own controls;
`start` hands it back to the policy.

## Model general-sequences:sequences:policy

A generic service (`rdk:service:generic`).

### Before you start

1. Deploy your policy: `seq deploy`. Its name is what you put in `policy`.
2. Give this machine a key of its own: `seq robot add --policy pick-cube_user`. The key is printed once.

### Configure

Add the module's environment with the key, so it is never in the service's attributes (anyone who can see the
machine's config reads those):

```json
{
  "modules": [
    {
      "type": "registry",
      "name": "general-sequences_sequences",
      "module_id": "general-sequences:sequences",
      "version": "latest",
      "env": { "SEQUENCES_API_KEY": "<the robot key>" }
    }
  ]
}
```

Then the service, naming the arm, gripper and cameras it drives:

```json
{
  "name": "sequences",
  "api": "rdk:service:generic",
  "model": "general-sequences:sequences:policy",
  "attributes": {
    "policy": "pick-cube_user",
    "hz": 15,
    "arm": "arm-1_user",
    "gripper": "gripper-1_user",
    "cameras": { "exterior_image_user": "cam-top_user", "wrist_image_user": "cam-wrist_user" },
    "instruction": "put the cube in the bowl"
  }
}
```

| Attribute | Required | What it is |
|---|---|---|
| `policy` | yes | Your deployed policy's name. |
| `hz` | yes | Steps a second: one row of the policy's answer is played each step. |
| `arm` | yes | The arm the policy drives. |
| `gripper` | no | The gripper the policy opens and closes. |
| `cameras` | no | A list of camera names, or a map from the key your policy reads a frame by to the camera. |
| `joints_key` | no | The key your policy reads the arm's joints by. Default `joints`. |
| `gripper_key` | no | The key your policy reads the gripper by. Default `gripper`. |
| `instruction` | no | A sentence handed to your policy with every observation. |
| `instruction_key` | no | The key it goes under. Default `instruction`. |
| `action_key` | no | Where the rows are when your policy answers a map. Default `actions`. |
| `replan_at` | no | Rows played after asking for an answer before the next is asked for. Default: all of them. |
| `valid_len` | no | Rows of an answer that are played. Default: all of them. |
| `joint_unit` | no | `radians` (default) or `degrees`: the unit your policy reads and answers joints in. |
| `gripper_threshold` | no | The gripper column at or above it closes the gripper. Default `0.5`. |
| `max_joint_step_deg` | no | A row that would move a joint further in one step stops the arm instead. Default `20`; `0` turns it off. |

### Commands

From the machine's page (or any Viam client), `do_command` with:

- `{"command": "start"}`: the policy drives the arm.
- `{"command": "stop"}`: the arm stops and the episode ends. Drive it by hand with Viam's controls.
- `{"command": "status"}`: `state` (`idle`, `starting`, `running`, `stopped` or `error`), `steps`, `acts`,
  `rows_played`, `holds` (steps with no row to play), `last_act_s` and `error`.

Every command answers with the status.

### What your policy reads and answers

Each step, your policy's observe function gets one observation:

- each camera's frame under its key, as an RGB image (height x width x 3, uint8);
- the arm's joints under `joints_key`, in `joint_unit`;
- the gripper under `gripper_key`: `1.0` once it was told to close, `0.0` otherwise;
- the `instruction`, when you set one.

Your policy answers rows, one a step: the arm's joints, then the gripper. A map works too, with the rows under
`action_key`. The module plays one row a step. Once `replan_at` rows have been played since it last asked, it asks
for the next answer while the arm keeps playing. The new answer starts where the arm is: as many rows in as were
played since asking.

### Safety

An answer is model output, not a safe command. Apart from `max_joint_step_deg`, this module checks nothing: your
arm's own limits apply. Keep an emergency stop within reach.
