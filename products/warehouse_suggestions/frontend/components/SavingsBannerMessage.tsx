import { humanizeBytes } from 'lib/utils/numbers'

import { SavingsSummary, countOf, spokenDuration } from '../suggestionCopy'

export interface SavingsBannerMessageProps {
    summary: SavingsSummary
}

export function SavingsBannerMessage({ summary }: SavingsBannerMessageProps): JSX.Element {
    const views = summary.timeViews + summary.bytesViews
    const time = summary.timeViews > 0 ? `~${spokenDuration(summary.savedSeconds, 1)}` : null
    const bytes = summary.bytesViews > 0 ? humanizeBytes(summary.savedBytes) : null

    return (
        <>
            <strong translate="no">{countOf(views, 'view', 'views')}</strong>
            <span> could save </span>
            {time && (
                <>
                    <strong translate="no" className="text-success">
                        {time}
                    </strong>
                    <span> of query time</span>
                </>
            )}
            {time && bytes && <span> and </span>}
            {bytes && (
                <>
                    <strong translate="no" className="text-success">
                        {bytes}
                    </strong>
                    <span> of scanning</span>
                </>
            )}
            <span> a month</span>
        </>
    )
}
