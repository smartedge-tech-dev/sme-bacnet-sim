"""Point behaviors: the sme-sim-common behavior engine plus the BACnet point-type rules."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sme_sim_common.behaviors import *  # noqa: F401,F403  (re-exported for existing imports)
from sme_sim_common.behaviors import (BEHAVIORS, Behavior, ExpressionError, Replay, ReplayTable,  # noqa: F401
                                      compile_expr, fmt_elapsed, ident, load_table, parse_elapsed, parse_iso)
from sme_sim_common.behaviors import make_behavior as _make_behavior

DISCRETE_PREFIXES = ("binary", "multi-state")


def is_discrete(obj_type: Optional[str]) -> bool:
    """Binary / multi-state objects always step-hold (a replayed state is never interpolated)."""
    return bool(obj_type) and obj_type.startswith(DISCRETE_PREFIXES)


def make_behavior(spec, base_dir: Optional[Path] = None, obj_type: Optional[str] = None) -> Optional[Behavior]:
    """Build a behavior for an object of type ``obj_type`` (``base_dir`` resolves relative replay files)."""
    return _make_behavior(spec, base_dir, discrete=is_discrete(obj_type))
