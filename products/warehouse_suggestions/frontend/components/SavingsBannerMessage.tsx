import { SavingsSummary, bannerSavings, certifyNote, countOf, summarySavings, unusedViewsNote } from '../suggestionCopy'

export interface SavingsBannerMessageProps {
    summary: SavingsSummary
    unusedViews: number
    toCertify?: number
}

export function SavingsBannerMessage({ summary, unusedViews, toCertify = 0 }: SavingsBannerMessageProps): JSX.Element {
    if (summary.views === 0 && unusedViews === 0) {
        return (
            <span translate="no">
                <strong>{countOf(toCertify, 'table or view', 'tables and views')}</strong>
                <span> to certify</span>
            </span>
        )
    }
    if (summary.views === 0) {
        return (
            <span translate="no">
                <strong>{countOf(unusedViews, 'unused view', 'unused views')}</strong>
                <span>{` to mark deprecated${certifyNote(toCertify)}`}</span>
            </span>
        )
    }
    const savings = summarySavings(summary)
    if (!savings) {
        return <LegacySavingsMessage summary={summary} unusedViews={unusedViews} toCertify={toCertify} />
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
                {`${savings.detail}${unusedViewsNote(unusedViews)}${certifyNote(toCertify)}`}
            </span>
        </span>
    )
}

function LegacySavingsMessage({ summary, unusedViews, toCertify = 0 }: SavingsBannerMessageProps): JSX.Element {
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
            <span translate="no">{`${unusedViewsNote(unusedViews)}${certifyNote(toCertify)}`}</span>
        </>
    )
}
