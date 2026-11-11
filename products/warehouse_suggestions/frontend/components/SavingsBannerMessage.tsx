import { SavingsSummary, bannerSavings, countOf, summarySavings, unusedViewsNote } from '../suggestionCopy'

export interface SavingsBannerMessageProps {
    summary: SavingsSummary
    unusedViews: number
}

export function SavingsBannerMessage({ summary, unusedViews }: SavingsBannerMessageProps): JSX.Element {
    if (summary.views === 0) {
        return (
            <span translate="no">
                <strong>{countOf(unusedViews, 'unused view', 'unused views')}</strong>
                <span> to mark deprecated</span>
            </span>
        )
    }
    const savings = summarySavings(summary)
    if (!savings) {
        return <LegacySavingsMessage summary={summary} unusedViews={unusedViews} />
    }
    return (
        <span className="flex flex-col gap-0.5">
            {savings.waiting ? (
                <span>
                    <span>People could wait </span>
                    <strong translate="no" className="text-success">
                        {savings.waiting}
                    </strong>
                    <span> less a month</span>
                </span>
            ) : (
                <span translate="no">{savings.headline}</span>
            )}
            <span translate="no" className="text-xs text-secondary">
                {`${savings.detail}${unusedViewsNote(unusedViews)}`}
            </span>
        </span>
    )
}

function LegacySavingsMessage({ summary, unusedViews }: SavingsBannerMessageProps): JSX.Element {
    return (
        <>
            <strong translate="no">{countOf(summary.views, 'view', 'views')}</strong>
            <span> could save </span>
            {bannerSavings(summary).map(({ amount, label }, index) => (
                <span key={label}>
                    {index > 0 && <span> and </span>}
                    <strong translate="no" className="text-success">
                        {amount}
                    </strong>
                    <span> {label}</span>
                </span>
            ))}
            <span> a month</span>
            <span translate="no">{unusedViewsNote(unusedViews)}</span>
        </>
    )
}
