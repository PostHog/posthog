import { LemonTag, Tooltip } from '@posthog/lemon-ui'

export function SuggestedReviewerScoutTag({ scoutName, reason }: { scoutName: string; reason?: string }): JSX.Element {
    // The tag is a div, so it needs a tab stop: the tooltip holds the only copy of the scout name.
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span>{scoutName}</span>
                    {reason && <p className="m-0">{reason}</p>}
                </div>
            }
            interactive={!!reason}
            openOnClick
        >
            <LemonTag type="muted" size="small" className="cursor-help" tabIndex={0}>
                Added by scout
            </LemonTag>
        </Tooltip>
    )
}
