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

from posthog import settings
from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    REPORT_SOURCES_COLUMNS,
    REPORT_SOURCES_EXTRA,
    SIGNAL_INSERTED_AT_COLUMN,
    Extras,
)
from products.signals.dags.inbox_ranking.common import partition_object_key, read_parquet_if_exists, snapshot_bounds
from products.signals.dags.inbox_ranking.dataset.dag import SIGNAL_EMBEDDINGS_TABLE

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


# A report groups signals that can arrive before it is born, so the sources read starts this many
# days before the training lookback.
REPORT_SOURCES_MARGIN_DAYS = 30


def load_report_sources(client, bucket: str, prefix: str, partition_key: str) -> pd.DataFrame | None:
    """The metadata columns of every `inbox_signal_embeddings` emission from the start of the
    training lookback, less `REPORT_SOURCES_MARGIN_DAYS`, to dt=D. The log holds only each day's
    inserts, so the frame is the union of the days. The vector column is never read. A missing
    earlier day is left out, but a missing dt=D returns None, because that day's sources are unknown."""
    end = datetime.date.fromisoformat(partition_key)
    days = settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS + REPORT_SOURCES_MARGIN_DAYS
    frames: list[pd.DataFrame] = []
    for offset in range(days + 1):
        day = (end - datetime.timedelta(days=offset)).isoformat()
        table = read_parquet_if_exists(
            client,
            bucket,
            partition_object_key(prefix, SIGNAL_EMBEDDINGS_TABLE, day),
            columns=list(REPORT_SOURCES_COLUMNS),
        )
        if table is None:
            if offset == 0:
                return None
            continue
        frames.append(table.to_pandas())
    return pd.concat(frames, ignore_index=True)


register_side_input(
    SideInputLoader(key=REPORT_SOURCES_EXTRA, as_of_column=SIGNAL_INSERTED_AT_COLUMN, load=load_report_sources)
)
