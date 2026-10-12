"""Grafana panel boxes mapped to the 12-column dashboard grid."""

from __future__ import annotations

from products.metrics.backend.dashboard_import.spec import GRID_COLUMNS, GridLayout

# Grafana draws a 24-column grid with 30 px rows and 8 px gaps. The dashboard grid has 80 px rows and 16 px gaps.
GRAFANA_COLUMNS = 24
GRAFANA_ROW_PX = 30
GRAFANA_GAP_PX = 8
ROW_PX = 80
GAP_PX = 16
MIN_INSIGHT_WIDTH = 2
MIN_INSIGHT_HEIGHT = 2


def _round_half_up(value: float) -> int:
    return int(value + 0.5)


def pixels_to_rows(pixels: float) -> int:
    return max(1, _round_half_up((pixels + GAP_PX) / (ROW_PX + GAP_PX)))


def grafana_height_to_rows(height: int) -> int:
    pixels = height * GRAFANA_ROW_PX + max(height - 1, 0) * GRAFANA_GAP_PX
    return pixels_to_rows(pixels)


def grafana_columns_to_grid(columns: int) -> int:
    return _round_half_up(columns * GRID_COLUMNS / GRAFANA_COLUMNS)


class GridPacker:
    """Places boxes top to bottom, so that a box never overlaps one that was placed before it."""

    def __init__(self) -> None:
        self._bottoms = [0] * GRID_COLUMNS

    def place(self, *, x: int, w: int, h: int) -> GridLayout:
        width = min(max(w, 1), GRID_COLUMNS)
        left = min(max(x, 0), GRID_COLUMNS - width)
        top = max(self._bottoms[left : left + width])
        height = max(h, 1)
        for column in range(left, left + width):
            self._bottoms[column] = top + height
        return GridLayout(x=left, y=top, w=width, h=height)

    def place_full_width(self, *, h: int) -> GridLayout:
        top = max(self._bottoms)
        height = max(h, 1)
        self._bottoms = [top + height] * GRID_COLUMNS
        return GridLayout(x=0, y=top, w=GRID_COLUMNS, h=height)

    def start_band(self) -> None:
        """Make the next boxes start below every box placed so far, as a Grafana row does."""
        self._bottoms = [max(self._bottoms)] * GRID_COLUMNS
