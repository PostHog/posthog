import { pluralize } from 'lib/utils/strings'

import type { ScanSkips } from './afterClickingScanLogic'

export function AfterClickingSkippedSessions({ skipped }: { skipped: ScanSkips }): JSX.Element | null {
    if (!skipped.busy && !skipped.quota) {
        return null
    }
    return (
        <>
            {skipped.busy > 0 ? (
                <span className="text-secondary text-sm">
                    <span>{skipped.busy}</span> {pluralize(skipped.busy, 'session', 'sessions', false)} weren't scanned
                    because Replay vision is busy. Ask again later to scan them.
                </span>
            ) : null}
            {skipped.quota > 0 ? (
                <span className="text-secondary text-sm">
                    <span>{skipped.quota}</span> {pluralize(skipped.quota, 'session', 'sessions', false)} weren't
                    scanned because your organization ran out of Replay vision credits.
                </span>
            ) : null}
        </>
    )
}
