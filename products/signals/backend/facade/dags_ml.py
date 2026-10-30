"""Dagster definitions for the inbox ranking model training that the core ``signals_ml`` location loads.

Kept apart from ``dags.py`` so that the ML location imports only the modules it registers.
"""

from products.signals.dags.inbox_ranking.common import is_inbox_ranking_registered
from products.signals.dags.inbox_ranking.nn import (
    dag as inbox_ranking_nn,
    experiments as inbox_ranking_nn_experiments,
    pairs as inbox_ranking_nn_pairs,
)

__all__ = [
    "inbox_ranking_nn",
    "inbox_ranking_nn_experiments",
    "inbox_ranking_nn_pairs",
    "is_inbox_ranking_registered",
]
