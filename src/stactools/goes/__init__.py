import stactools.core
from .dataset import Dataset
from .errors import CogifyError

stactools.core.use_fsspec()


def register_plugin(registry):
    from . import commands
    registry.register_subcommand(commands.create_goes_command)


__all__ = [Dataset, CogifyError]
__version__ = '0.1.4'
"""Library version"""
