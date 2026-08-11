// Report ids already reported as `Inbox report opened` in this browser session, kept in
// sessionStorage. sessionStorage is per tab and survives a page reload, so a cold reload of a
// still-open tab can tell it is re-showing a report it already counted and suppress the duplicate
// open — rather than logging a phantom `deeplink` open every time a pile of left-open tabs reloads.
const SESSION_STORAGE_KEY = 'inbox_opened_report_ids'

function readOpenedReportIds(): Set<string> {
    try {
        const raw = sessionStorage.getItem(SESSION_STORAGE_KEY)
        return raw ? new Set(JSON.parse(raw) as string[]) : new Set()
    } catch {
        // sessionStorage may be unavailable (private mode, disabled) or hold corrupt data; treat
        // as no history so tracking falls back to the prior per-load behavior.
        return new Set()
    }
}

export function hasReportBeenOpenedThisSession(reportId: string): boolean {
    return readOpenedReportIds().has(reportId)
}

export function markReportOpenedThisSession(reportId: string): void {
    try {
        const ids = readOpenedReportIds()
        ids.add(reportId)
        sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify([...ids]))
    } catch {
        // Non-fatal: without persistence a later reload just can't dedupe this report's open.
    }
}
