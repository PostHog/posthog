"""In-flight apply caps shared by the enqueue-claim layer and the temporal package.

A leaf module: `enqueue_claims` needs these, and importing them from `temporal.constants` would load
the whole temporal package, whose activities import `enqueue_claims` back.
"""

# Hard ceiling on a single scanner's concurrently-running apply-scanner workflows. Bounds one bad config
# (broad filter on a high-volume team) from monopolising the shared rasterizer queue + provider concurrency.
MAX_IN_FLIGHT_APPLIES_PER_SCANNER = 150
# Team-wide ceiling across all of a team's scanners and on-demand triggers, so N scanners can't hold
# N x 150 rasterizer slots. Fairness only; the rasterizer scales horizontally for total throughput.
MAX_IN_FLIGHT_APPLIES_PER_TEAM = 300

# Slots at each cap that scheduled dispatch (sweep, backfill) must leave free, so a user-initiated
# observe still admits when scheduled work is saturated; on-demand admission checks the full caps.
ON_DEMAND_RESERVED_SCANNER_SLOTS = 25
ON_DEMAND_RESERVED_TEAM_SLOTS = 50

# A backfill's dispatches count toward the shared per-scanner/per-team caps but never fill more than
# this many slots, so live sweeps always retain rasterizer + provider capacity.
MAX_IN_FLIGHT_APPLIES_PER_BACKFILL = 50
