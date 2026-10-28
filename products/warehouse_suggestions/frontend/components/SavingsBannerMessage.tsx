import { SavingsSummary, countOf, namedSaving } from '../suggestionCopy'

export interface SavingsBannerMessageProps {
    summary: SavingsSummary
}

export function SavingsBannerMessage({ summary }: SavingsBannerMessageProps): JSX.Element {
    const { time, bytes } = namedSaving(summary.saving, 1)

    return (
        <>
            <strong translate="no">{countOf(summary.views, 'view', 'views')}</strong>
            <span> could save </span>
            {time && (
                <>
                    <strong translate="no" className="text-success">
                        {`~${time}`}
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
