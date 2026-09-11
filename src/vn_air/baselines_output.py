"""Phase 8 baseline artifact writers.

Kept separate from the calculation module so output serialization can be
replayed and audited without adding database or modeling dependencies.
"""

from vn_air.baselines import (
    assumptions_markdown,
    replay_baselines,
    sha256_file,
    write_csv,
    write_outputs,
)

__all__ = ["assumptions_markdown", "replay_baselines", "sha256_file", "write_csv", "write_outputs"]
