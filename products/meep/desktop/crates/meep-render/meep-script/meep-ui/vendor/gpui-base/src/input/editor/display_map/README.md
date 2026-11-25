# Display Mapping System

Layered coordinate conversion and code folding for Editor/Input.

## Architecture

```
Buffer (Rope)              Logical text
    ↓
WrapMap                    Soft-wrapping (buffer_line ↔ wrap_row)
    ↓
FoldMap                    Fold projection (wrap_row ↔ display_row)
    ↓
DisplayMap                 Public facade (BufferPos ↔ DisplayPos)
```

## Coordinate Systems

| Type | Fields | Scope | Description |
|------|--------|-------|-------------|
| `BufferPos` | `{ line, col }` | public | Logical line/column in Rope |
| `WrapPos` | `{ row, col }` | internal | Visual row after soft-wrapping |
| `DisplayPos` | `{ row, col }` | public | Final visible row after folding |

## Modules

### `DisplayMap` — Public facade

- `buffer_pos_to_display_pos()` / `display_pos_to_buffer_pos()`
- `set_fold_candidates()`, `toggle_fold()`, `is_folded_at()`, `clear_folds()`
- `on_text_changed()`, `on_layout_changed()`, `set_font()`
- `adjust_folds_for_edit()` — incremental fold/candidate line-delta adjustment
- `update_fold_candidates_for_edit()` — region-scoped candidate extraction after edits

### `WrapMap` — Soft-wrapping layer

Built on `TextWrapper`. Provides buffer ↔ wrap coordinate mapping with prefix sum cache for O(1) line lookups.

### `FoldMap` — Fold projection layer

Stores the projection as sorted, merged runs of hidden wrap rows (`HiddenRows`), each carrying a running `hidden_before` count of the rows the earlier runs hide. Rebuilding costs O(folds), not O(document rows), and every mapping in either direction is a `partition_point` binary search over the runs. When no folds are active, uses identity mapping (wrap_row == display_row) without any runs.

### `FoldRange` / `folding` — Fold extraction

- `extract_fold_ranges(tree)` — full tree traversal (initial load only)
- `extract_fold_ranges_in_range(tree, byte_range)` — region-scoped traversal for edits, skips subtrees outside range
