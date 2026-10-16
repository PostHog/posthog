import type { GENERATED_TOOLS } from '@/tools/generated/experiments'

/**
 * One row per experiment tool that has `param_overrides: { id: ... }` in
 * products/experiments/mcp/tools.yaml, with stand-in values for the tool's other
 * required inputs so a parameterised assertion can build a minimal valid input for
 * every shape. The id cast test and the id alias test both parse against this table,
 * so adding a cast'd or aliased experiment tool means appending one row here.
 */
export const EXPERIMENT_ID_TOOLS = [
    ['experiment-activity', {}],
    ['experiment-archive', {}],
    ['experiment-cleanup-task', {}],
    ['experiment-copy-to-project', { target_team_id: 5 }],
    ['experiment-delete', {}],
    ['experiment-duplicate', { name: 'A duplicate', feature_flag_key: 'duplicated-flag' }],
    ['experiment-end', {}],
    ['experiment-freeze-exposure', {}],
    ['experiment-get', {}],
    ['experiment-launch', {}],
    ['experiment-metrics-recalculation-create', {}],
    ['experiment-metrics-recalculation-latest-retrieve', {}],
    ['experiment-metrics-recalculation-retrieve', { recalculation_id: '0199a1c0-0000-7000-8000-000000000000' }],
    ['experiment-migrate', {}],
    ['experiment-pause', {}],
    ['experiment-reset', {}],
    ['experiment-resume', {}],
    ['experiment-ship-variant', { variant_key: 'test' }],
    ['experiment-timeseries-results', { metric_uuid: 'metric-uuid', fingerprint: 'fp' }],
    ['experiment-unarchive', {}],
    ['experiment-unfreeze-exposure', {}],
    ['experiment-update', {}],
    ['experiments-session-event-deltas-create', {}],
] as const satisfies ReadonlyArray<readonly [keyof typeof GENERATED_TOOLS, Record<string, unknown>]>
