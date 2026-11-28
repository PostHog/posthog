"""Releases' sources for work threads. Today finds this module by name."""

from products.today.backend.facade.contracts import WorkSource

from ..today_work import find_release_work_threads

WORK_SOURCES = (WorkSource(name="release", find=find_release_work_threads, scopes=("feature_flag:read",)),)
