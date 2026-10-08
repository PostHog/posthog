import { PromiseTimeoutError, withTimeout } from 'lib/utils/async'

import { capturePanelLoadTimedOut } from '../inboxAnalytics'
import type { InboxPanelLoad } from '../inboxAnalytics'

/**
 * How long a side-panel read may stay in flight. A panel shows its spinner while the loader flag is
 * true and reaches its retry branch only once the read settles, so a read that never settles leaves
 * the pane with no way out. Well above a healthy read, so a slow but live one still lands.
 */
export const PANEL_LOAD_TIMEOUT_MS = 20_000

/**
 * Bound a panel's read, so one that never settles fails the loader and reaches whatever the panel
 * renders for a failed load. A read that never settles writes no `client_request_failure` row, so
 * the expiry is the only place it can be counted.
 */
export async function withPanelLoadTimeout<T>(
    load: InboxPanelLoad,
    request: (options: RequestInit) => Promise<T>
): Promise<T> {
    try {
        return await withTimeout((signal) => request({ signal }), PANEL_LOAD_TIMEOUT_MS, `${load} load timed out`)
    } catch (error) {
        if (error instanceof PromiseTimeoutError) {
            capturePanelLoadTimedOut({ load, timeoutMs: PANEL_LOAD_TIMEOUT_MS })
        }
        throw error
    }
}
