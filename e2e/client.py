"""
Drive the service on a running viam-server as a person would from the machine's page: status, start, wait until it has
played a few answers (a worker that is starting can take minutes), status, stop. Prints one JSON line: the arm's joints
before and after, the gripper, and each status.

    python e2e/client.py [seconds to wait, 300]
"""
import asyncio
import json
import sys
import time

from viam.components.arm import Arm
from viam.errors import ResourceNotFoundError
from viam.robot.client import RobotClient
from viam.rpc.dial import DialOptions
from viam.services.generic import Generic


async def main(wait_s: float) -> None:
    robot = await RobotClient.at_address(
        "localhost:8080", RobotClient.Options(refresh_interval=0, dial_options=DialOptions(insecure=True,
                                                                                           disable_webrtc=True)))
    try:
        arm = Arm.from_robot(robot, "arm")
        ready_by = time.monotonic() + 600            # the module's first run makes its Python environment
        while True:
            try:
                service = Generic.from_robot(robot, "sequences")
                break
            except ResourceNotFoundError:
                if time.monotonic() > ready_by:
                    raise
                await asyncio.sleep(5)
                await robot.refresh()
        before = list((await arm.get_joint_positions()).values)
        idle = await service.do_command({"command": "status"})
        started = await service.do_command({"command": "start"})
        deadline = time.monotonic() + wait_s
        running = started
        while time.monotonic() < deadline:
            running = await service.do_command({"command": "status"})
            if running["state"] == "error" or (running["state"] == "running" and running["acts"] >= 4):
                break
            await asyncio.sleep(2)
        after = list((await arm.get_joint_positions()).values)
        stopped = await service.do_command({"command": "stop"})
        print(json.dumps({"before": before, "after": after, "idle": idle, "started": started, "running": running,
                          "stopped": stopped}, default=str))
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 300))
