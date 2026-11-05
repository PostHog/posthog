import { ApiConfig } from 'lib/api'
import { PromiseTimeoutError, withTimeout } from 'lib/utils/async'

import { signalsReportsStateCreate } from 'products/signals/frontend/generated/api'
import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import { captureWriteTimedOut } from '../inboxAnalytics'
import type { InboxWrite } from '../inboxAnalytics'
import type { SignalReport, SignalReportStateRequest } from '../types'

/**
 * How long a report write may stay in flight. A control stays disabled until its write settles, so a write that
 * never settles leaves the control disabled with no way out. Well above a healthy write, so a slow but live one
 * still lands.
 */
export const INBOX_WRITE_TIMEOUT_MS = 30_000

/**
 * Bound a report write, so one that never settles fails and reaches the caller's error path. The server can still
 * apply a write that timed out, so callers reload after a failure instead of trusting their local copy.
 */
export async function withInboxWriteTimeout<T>(
    write: InboxWrite,
    request: (options: { signal: AbortSignal }) => Promise<T>
): Promise<T> {
    try {
        return await withTimeout((signal) => request({ signal }), INBOX_WRITE_TIMEOUT_MS, `${write} write timed out`)
    } catch (error) {
        if (error instanceof PromiseTimeoutError) {
            captureWriteTimedOut({ write, timeoutMs: INBOX_WRITE_TIMEOUT_MS })
        }
        throw error
    }
}

export function setReportState(reportId: SignalReport['id'], data: SignalReportStateRequest): Promise<SignalReportApi> {
    return withInboxWriteTimeout('state', (options) =>
        signalsReportsStateCreate(String(ApiConfig.getCurrentProjectId()), reportId, data, options)
    )
}
