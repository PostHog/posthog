import { countsPartialDays } from './intentDateRange'

/** Says where intent topics count differently from the page around them: shared filters and partial days. */
export function IntentTopicsScopeNote({
    filtersIgnored,
    dateFrom,
    dateTo,
}: {
    filtersIgnored: boolean
    dateFrom: string | null
    dateTo: string | null
}): JSX.Element | null {
    const partialDays = countsPartialDays(dateFrom, dateTo)
    if (!filtersIgnored && !partialDays) {
        return null
    }
    return (
        <div className="flex flex-col text-xs text-secondary" data-attr="mcp-intent-topics-scope-note">
            {filtersIgnored ? (
                <span>The filters above don't apply to intent topics. They count every call in the date range.</span>
            ) : null}
            {partialDays ? (
                <span>Intent topics are counted by whole day, so they include every day the date range touches.</span>
            ) : null}
        </div>
    )
}
