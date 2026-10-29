import type { AutomaticFlashForEnumApi } from 'products/review_hog/frontend/generated/api.schemas'

/** How much of the team a rule reviews: a filled circle for everyone, an open one for some people, grey for nobody. */
export function RuleStateIcon({ flashFor }: { flashFor: AutomaticFlashForEnumApi }): JSX.Element {
    return (
        <span
            className={`inline-flex shrink-0 ${flashFor === 'off' ? 'text-border-bold' : 'text-success'}`}
            aria-hidden
        >
            <svg width="12" height="12" viewBox="0 0 12 12">
                {flashFor === 'listed' ? (
                    <circle cx="6" cy="6" r="4.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
                ) : (
                    <circle cx="6" cy="6" r="5.5" fill="currentColor" />
                )}
            </svg>
        </span>
    )
}
