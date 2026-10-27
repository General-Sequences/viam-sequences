import asyncio

from viam.module.module import Module

from models.policy import SequencesPolicy  # noqa: F401 - importing it registers the model

if __name__ == "__main__":
    asyncio.run(Module.run_from_registry())
