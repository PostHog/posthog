"""Per-touchpoint credit weights for each attribution model.

Every builder returns an array expression parallel to `filtered_ts` (the touchpoint timestamps inside the
attribution window, ascending or not — order is never assumed). Weights sum to 1.0 per conversion, so
summing a model's weights across every row reproduces the total conversion count.

Because all five builders map over the same `filtered_ts`, their outputs are guaranteed to be the same
length. That's what lets a caller emit all five arrays and explode them with a single shared
`ARRAY JOIN arrayEnumerate(...)`, computing every model in one pass over the events table.

Caller beware: `filtered_ts` is substituted inside `arrayMap` lambdas, so if it's a bare field reference
its name must not collide with a lambda parameter used below — `ts`, `w`, `_x`, `_pw`, `_j`. A collision
resolves the reference to the scalar lambda argument instead of the array, which ClickHouse rejects with
"argument for function arrayMin must be array".
"""

import math

from posthog.hogql import ast

DAY_IN_SECONDS = 86400
LN2 = math.log(2)  # ≈ 0.693, used in half-life formula: weight = exp(-ln(2) * t / half_life)
# Half-life = attribution_window / 4, so a 90-day window gives ~22.5-day half-life.
# At t = half_life, weight = exp(-ln(2)) = 0.5 (exactly half).
# This follows the industry standard (Google Analytics, Adobe, Mixpanel all use 7-day half-life).
TIME_DECAY_HALF_LIFE_DIVISOR = 4


def build_linear_weights(filtered_ts: ast.Expr) -> ast.Expr:
    """Equal weight for all touchpoints: 1.0 / n."""
    n = ast.Call(name="toFloat", args=[ast.Call(name="length", args=[filtered_ts])])
    return ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=["_x"],
                expr=ast.ArithmeticOperation(
                    left=ast.Constant(value=1.0),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(name="greatest", args=[n, ast.Constant(value=1.0)]),
                ),
            ),
            filtered_ts,
        ],
    )


def build_time_decay_weights(
    filtered_ts: ast.Expr, conversion_time: ast.Expr, attribution_window_seconds: int
) -> ast.Expr:
    """Exponential half-life decay: weight = exp(-ln(2) * delta / half_life).

    At t = half_life, weight = 0.5 (exactly half). This matches the industry
    standard used by Google Analytics, Adobe Analytics, and Mixpanel.
    The half-life scales with the attribution window (window / 4).
    Weights are normalized so they sum to 1.
    """
    half_life_seconds = max(attribution_window_seconds // TIME_DECAY_HALF_LIFE_DIVISOR, DAY_IN_SECONDS)
    # weight = exp(-ln(2) * (conversion_time - ts) / half_life)
    raw_weights = ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=["ts"],
                expr=ast.Call(
                    name="exp",
                    args=[
                        ast.ArithmeticOperation(
                            left=ast.Constant(value=-LN2),
                            op=ast.ArithmeticOperationOp.Mult,
                            right=ast.ArithmeticOperation(
                                left=ast.ArithmeticOperation(
                                    left=conversion_time,
                                    op=ast.ArithmeticOperationOp.Sub,
                                    right=ast.Field(chain=["ts"]),
                                ),
                                op=ast.ArithmeticOperationOp.Div,
                                right=ast.Constant(value=half_life_seconds),
                            ),
                        ),
                    ],
                ),
            ),
            filtered_ts,
        ],
    )
    # Normalize: divide each weight by sum of all weights.
    # Note: raw_weights AST node is referenced twice (in arraySum and as the
    # arrayMap input), so ClickHouse evaluates the exp() computation twice per row.
    # This is acceptable because touchpoint arrays are small (typically 3-10 elements).
    weight_sum = ast.Call(name="arraySum", args=[raw_weights])
    return ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=["w"],
                expr=ast.ArithmeticOperation(
                    left=ast.Field(chain=["w"]),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(name="greatest", args=[weight_sum, ast.Constant(value=0.000001)]),
                ),
            ),
            raw_weights,
        ],
    )


def build_position_based_weights(filtered_ts: ast.Expr) -> ast.Expr:
    """40% first touch, 40% last touch, 20% distributed among middle touchpoints.

    Uses arrayMin/arrayMax to identify first/last by timestamp value,
    avoiding dependency on array ordering (groupArray doesn't guarantee order).

    Edge cases:
    - 0 touchpoints: empty array (ARRAY JOIN produces no rows)
    - 1 touchpoint: [1.0]
    - 2 touchpoints: [0.5, 0.5]
    - Duplicate timestamps: if multiple touchpoints share min/max timestamp,
      all get 0.4 weight before normalization. Normalization rescues the total
      to 1.0, but credit distribution may deviate from the intended 40/20/40.
    """
    n = ast.Call(name="toFloat", args=[ast.Call(name="length", args=[filtered_ts])])
    middle_weight = ast.ArithmeticOperation(
        left=ast.Constant(value=0.2),
        op=ast.ArithmeticOperationOp.Div,
        right=ast.Call(
            name="greatest",
            args=[
                ast.ArithmeticOperation(
                    left=n,
                    op=ast.ArithmeticOperationOp.Sub,
                    right=ast.Constant(value=2.0),
                ),
                ast.Constant(value=1.0),
            ],
        ),
    )

    min_ts = ast.Call(name="arrayMin", args=[filtered_ts])
    max_ts = ast.Call(name="arrayMax", args=[filtered_ts])

    position_weights = ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=["ts"],
                expr=ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["ts"]),
                            op=ast.CompareOperationOp.Eq,
                            right=min_ts,
                        ),
                        ast.Constant(value=0.4),
                        ast.Call(
                            name="if",
                            args=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=["ts"]),
                                    op=ast.CompareOperationOp.Eq,
                                    right=max_ts,
                                ),
                                ast.Constant(value=0.4),
                                middle_weight,
                            ],
                        ),
                    ],
                ),
            ),
            filtered_ts,
        ],
    )

    # Normalize so weights always sum to 1.0.
    # Handles edge cases like duplicate timestamps where multiple elements
    # match arrayMin/arrayMax.
    # Wrap in ifNull to handle Nullable(Float64) from HogQL casts.
    non_nullable_weights = ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=["_pw"],
                expr=ast.Call(name="ifNull", args=[ast.Field(chain=["_pw"]), ast.Constant(value=0.0)]),
            ),
            position_weights,
        ],
    )
    weight_sum = ast.Call(name="arraySum", args=[non_nullable_weights])
    normalized_weights = ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=["w"],
                expr=ast.ArithmeticOperation(
                    left=ast.Field(chain=["w"]),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(name="greatest", args=[weight_sum, ast.Constant(value=0.000001)]),
                ),
            ),
            non_nullable_weights,
        ],
    )

    return ast.Call(
        name="if",
        args=[
            # n == 0: no touchpoints in window, empty weights (ARRAY JOIN produces no rows)
            ast.CompareOperation(
                left=ast.Call(name="length", args=[filtered_ts]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=0),
            ),
            ast.Array(exprs=[]),
            ast.Call(
                name="if",
                args=[
                    # n == 1: single touchpoint gets all credit
                    ast.CompareOperation(
                        left=ast.Call(name="length", args=[filtered_ts]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=1),
                    ),
                    ast.Array(exprs=[ast.Constant(value=1.0)]),
                    ast.Call(
                        name="if",
                        args=[
                            # n == 2: [0.5, 0.5]
                            ast.CompareOperation(
                                left=ast.Call(name="length", args=[filtered_ts]),
                                op=ast.CompareOperationOp.Eq,
                                right=ast.Constant(value=2),
                            ),
                            ast.Array(exprs=[ast.Constant(value=0.5), ast.Constant(value=0.5)]),
                            # n >= 3: assign by min/max timestamp, normalized
                            normalized_weights,
                        ],
                    ),
                ],
            ),
        ],
    )


def _build_single_touch_weights(filtered_ts: ast.Expr, extreme: str) -> ast.Expr:
    """All credit to the touchpoint at the min (first) or max (last) timestamp.

    `indexOf` returns the position of the *first* match, so exactly one element gets 1.0 even when
    several touchpoints share the extreme timestamp. That matches how the single-touch attribution path
    resolves ties, and keeps the weights summing to exactly 1.0 without a normalization step.
    """
    return ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=["_j"],
                expr=ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["_j"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Call(
                                name="indexOf",
                                args=[filtered_ts, ast.Call(name=extreme, args=[filtered_ts])],
                            ),
                        ),
                        ast.Constant(value=1.0),
                        ast.Constant(value=0.0),
                    ],
                ),
            ),
            ast.Call(name="arrayEnumerate", args=[filtered_ts]),
        ],
    )


def build_first_touch_weights(filtered_ts: ast.Expr) -> ast.Expr:
    """All credit to the earliest touchpoint in the window."""
    return _build_single_touch_weights(filtered_ts, "arrayMin")


def build_last_touch_weights(filtered_ts: ast.Expr) -> ast.Expr:
    """All credit to the latest touchpoint in the window."""
    return _build_single_touch_weights(filtered_ts, "arrayMax")
