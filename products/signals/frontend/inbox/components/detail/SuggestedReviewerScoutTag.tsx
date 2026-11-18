import { LemonTag, Tooltip } from '@posthog/lemon-ui'

export function SuggestedReviewerScoutTag({ scoutNames }: { scoutNames: string[] }): JSX.Element {
    // The tag is a div, so it needs a tab stop: the tooltip holds the only copy of the scout names.
    return (
        <Tooltip
            title={
                <div className="flex flex-col">
                    {scoutNames.map((scoutName) => (
                        <span key={scoutName}>{scoutName}</span>
                    ))}
                </div>
            }
        >
            <LemonTag type="muted" size="small" className="cursor-help" tabIndex={0}>
                Added by scout
            </LemonTag>
        </Tooltip>
    )
}
