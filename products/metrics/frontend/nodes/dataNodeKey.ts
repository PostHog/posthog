import { InsightLogicProps } from '~/types'

/**
 * The `dataNodeLogic` key for a metrics node, derived from the query it loads.
 *
 * Do not use a per-mount counter here. React can render a component many times without committing it,
 * for example when a concurrent render restarts. Each of those renders mounts the logic from inside
 * render through `useValues`, and that mount is never undone. With a new key per render, every
 * restart mounts one more logic, starts one more load, and changes the store. That store change
 * restarts the render again, so the node never commits and the loads queue up without end.
 * A key that depends only on the query lets every render attempt reuse the logic that is already mounted.
 *
 * The key holds the whole serialized query rather than a hash of it, because two different queries
 * that shared a key would share one logic and keep replacing each other's query and reloading.
 * A saved insight's id is part of the key, so two tiles with the same query keep their own cached results.
 */
export function metricsDataNodeKey(
    prefix: string,
    query: object,
    insightProps: Pick<InsightLogicProps, 'dashboardItemId'> | undefined
): string {
    const owner = insightProps?.dashboardItemId ? `${insightProps.dashboardItemId}.` : ''
    return `${prefix}.${owner}${JSON.stringify(query)}`
}
