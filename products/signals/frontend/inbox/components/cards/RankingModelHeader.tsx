const COMPARISON = 'How likely, compared with the average report'

/**
 * The model heading on the ranking hover cards. The Recommended and Personalized cards share it, so
 * the two cards describe the scores with the same words. `note` adds a sentence after the comparison.
 */
export function RankingModelHeader({ note }: { note?: string }): JSX.Element {
    return (
        <div>
            <div className="text-sm font-semibold">We trained an ML model. Yay!</div>
            <div className="opacity-70">{note ? `${COMPARISON}. ${note}` : COMPARISON}</div>
        </div>
    )
}
