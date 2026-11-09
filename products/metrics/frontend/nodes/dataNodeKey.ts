import { hashCodeForString } from 'lib/utils/strings'

/**
 * The `dataNodeLogic` key for a metrics node, derived from the query it loads.
 *
 * Do not use a per-mount counter here. React can render a component many times without committing it,
 * for example when a concurrent render restarts. Each of those renders mounts the logic from inside
 * render through `useValues`, and that mount is never undone. With a new key per render, every
 * restart mounts one more logic, starts one more load, and changes the store. That store change
 * restarts the render again, so the node never commits and the loads queue up without end.
 * A key that depends only on the query lets every render attempt reuse the logic that is already mounted.
 */
export function metricsDataNodeKey(prefix: string, query: object): string {
    return `${prefix}.${hashCodeForString(JSON.stringify(query))}`
}
