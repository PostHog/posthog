import { SavingsSummary, bannerSavings, countOf, summarySavings } from '../suggestionCopy'

export interface SavingsBannerMessageProps {
    summary: SavingsSummary
}

export function SavingsBannerMessage({ summary }: SavingsBannerMessageProps): JSX.Element {
    const savings = summarySavings(summary)
    if (!savings) {
        return <LegacySavingsMessage summary={summary} />
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
                {savings.detail}
            </span>
        </span>
    )
}

function LegacySavingsMessage({ summary }: SavingsBannerMessageProps): JSX.Element {
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
        </>
    )
}
