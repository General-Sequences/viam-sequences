"""
The end-to-end check's policy: it reads what the module observes - a camera frame under "front", the arm's joints in
radians under "joints", the gripper - and answers ten rows, each moving every joint 0.01 rad further from where it was
asked (the other way if the frame is not a real HxWx3 uint8 image), the gripper closed from the sixth row on. The arm
climbing is the proof that frames and joints went in and rows came out.

    seq deploy e2e/policy/viam_e2e_user.py
"""
import numpy as np

import seq


@seq.policy(gpu="cpu", hz=10, action_chunk_valid_len=10, action_chunk_replan_at=5, name="viam-e2e")
class ViamE2E_user:
    @seq.observe
    def take(self, obs):
        self.obs = obs

    @seq.infer
    def answer(self):
        frame, joints = self.obs["front"], np.asarray(self.obs["joints"], dtype=np.float64)
        seen = frame.ndim == 3 and frame.shape[2] == 3 and frame.dtype == np.uint8 and frame.size > 0
        step = 0.01 if seen else -0.01
        rows = [np.append(joints + step * (i + 1), 1.0 if i >= 5 else 0.0) for i in range(10)]
        return {"actions": np.stack(rows).astype(np.float32), "frame": list(frame.shape)}
