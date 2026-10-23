"""Tile boxes on the 12-column dashboard grid, from Grafana panel boxes or from boxes read in a screenshot."""

from __future__ import annotations

from posthog.dataclasses import frozen

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


@frozen
class RequestedBox:
    """A box that an agent read from a screenshot, with the smallest size its tile can have."""

    key: str
    layout: GridLayout
    min_w: int = 1
    min_h: int = 1


def _fit_widths(wanted: list[int], minimums: list[int]) -> list[int]:
    """Share the grid columns in proportion to the wanted widths. No width goes below its minimum."""
    total = sum(wanted)
    exact = [width * GRID_COLUMNS / total for width in wanted]
    widths = [max(int(share), minimum) for share, minimum in zip(exact, minimums)]
    by_remainder = sorted(range(len(widths)), key=lambda index: exact[index] - int(exact[index]), reverse=True)
    while sum(widths) < GRID_COLUMNS:
        for index in by_remainder:
            if sum(widths) == GRID_COLUMNS:
                break
            widths[index] += 1
    while sum(widths) > GRID_COLUMNS:
        index = max((index for index in range(len(widths)) if widths[index] > minimums[index]), key=lambda i: widths[i])
        widths[index] -= 1
    return widths


def _split_lines(row: list[RequestedBox]) -> list[list[RequestedBox]]:
    """Split a row that is too wide into lines of about equal size, so that each line fits the grid."""
    for count in range(1, len(row) + 1):
        size = -(-len(row) // count)
        lines = [row[start : start + size] for start in range(0, len(row), size)]
        if all(sum(box.min_w for box in line) <= GRID_COLUMNS for line in lines):
            return lines
    return [[box] for box in row]


def place_screenshot_boxes(boxes: list[RequestedBox]) -> dict[str, GridLayout]:
    """Place the boxes of a screenshot so that no two overlap, and boxes in one row stay side by side.

    An agent reads the boxes by eye, so a row can overlap or be wider than the grid after the minimum
    sizes apply. Such a row shares the grid width in proportion to the widths the agent read, and a row
    that cannot fit even at the minimum widths wraps onto more lines.
    """
    rows: dict[int, list[RequestedBox]] = {}
    for box in sorted(boxes, key=lambda box: (box.layout.y, box.layout.x)):
        rows.setdefault(max(box.layout.y, 0), []).append(box)
    packer = GridPacker()
    placed: dict[str, GridLayout] = {}
    for row in rows.values():
        widths = [min(max(box.layout.w, box.min_w), GRID_COLUMNS) for box in row]
        if sum(widths) <= GRID_COLUMNS:
            cursor = 0
            for index, (box, width) in enumerate(zip(row, widths)):
                # Keep the gap the agent read, but leave room for the boxes that follow in the row.
                room = GRID_COLUMNS - sum(widths[index:])
                left = min(max(box.layout.x, cursor), room)
                placed[box.key] = packer.place(x=left, w=width, h=max(box.layout.h, box.min_h))
                cursor = left + width
            continue
        for line in _split_lines(row):
            fitted = _fit_widths([max(box.layout.w, 1) for box in line], [box.min_w for box in line])
            cursor = 0
            for box, width in zip(line, fitted):
                placed[box.key] = packer.place(x=cursor, w=width, h=max(box.layout.h, box.min_h))
                cursor += width
    return placed
