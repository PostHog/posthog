"""The registry of side-input loaders an experiment family can read beside the report vectors.

A side input is a per-report frame that a feature set reads through its `extras_keys`. Each row
must carry the moment it became known, in the column the loader declares as `as_of_column`. The
registry refuses a frame without that column, with a null in it, or with a naive timestamp, and it
drops the rows that became known after the partition ends. A feature set then reads the frame
through `rows_as_of`, which keeps only the rows known at the moment being built. A side input that
changes over a report's life therefore cannot leak a later value into an earlier example.

A missing object leaves its key out of the result, so only the families that read it skip. An empty
object keeps its key.
"""

import datetime
from collections.abc import Callable, Iterable

import pandas as pd

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import Extras
from products.signals.dags.inbox_ranking.common import snapshot_bounds

# Reads the dt=D object of one side input. Returns None when the object was never written.
LoadFrame = Callable[[object, str, str, str], pd.DataFrame | None]


class SideInputError(ValueError):
    pass


@frozen
class SideInputLoader:
    key: str
    as_of_column: str
    load: LoadFrame


SIDE_INPUT_LOADERS: dict[str, SideInputLoader] = {}


def register_side_input(loader: SideInputLoader) -> SideInputLoader:
    if loader.key in SIDE_INPUT_LOADERS:
        raise SideInputError(f"side input {loader.key} is registered twice")
    if not loader.as_of_column:
        raise SideInputError(f"side input {loader.key} declares no as_of_column")
    SIDE_INPUT_LOADERS[loader.key] = loader
    return loader


def _known_by(frame: pd.DataFrame, loader: SideInputLoader, as_of: datetime.datetime) -> pd.DataFrame:
    if as_of.tzinfo is None:
        raise SideInputError(f"side input {loader.key} needs a timezone-aware as_of")
    if loader.as_of_column not in frame:
        raise SideInputError(f"side input {loader.key} has no {loader.as_of_column} column")
    known = frame[loader.as_of_column]
    if known.isna().any():
        raise SideInputError(f"side input {loader.key} has rows with no {loader.as_of_column}")
    if not isinstance(known.dtype, pd.DatetimeTZDtype):
        raise SideInputError(f"side input {loader.key} column {loader.as_of_column} is not a timezone-aware timestamp")
    return frame.loc[known <= as_of]


def rows_as_of(extras: Extras, key: str, as_of: datetime.datetime | None) -> pd.DataFrame:
    """The rows of side input `key` known at `as_of`. A feature set reads a registered side input
    through this, so a moment never sees a value that landed after it."""
    if as_of is None:
        raise SideInputError(f"side input {key} is read only as of a moment")
    return _known_by(extras[key], SIDE_INPUT_LOADERS[key], as_of)


def load_side_inputs(client, bucket: str, prefix: str, partition_key: str, keys: Iterable[str]) -> Extras:
    """The dt=D frame of each side input in `keys`, cut at the end of dt=D. A key without a
    registered loader raises, and a key whose object is missing is left out."""
    _, snapshot_end = snapshot_bounds(partition_key)
    loaded: dict[str, pd.DataFrame] = {}
    for key in keys:
        loader = SIDE_INPUT_LOADERS.get(key)
        if loader is None:
            raise SideInputError(f"side input {key} has no registered loader")
        frame = loader.load(client, bucket, prefix, partition_key)
        if frame is not None:
            loaded[key] = _known_by(frame, loader, snapshot_end)
    return loaded
