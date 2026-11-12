import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { ErrorTrackingIssueTag } from '~/queries/schema/schema-general'

function answeredBy(source: string | undefined): string | null {
    switch (source) {
        case 'jev':
            return 'Answered by AI'
        case 'manual':
            return 'Set manually'
        default:
            return null
    }
}

export function IssueTags({ tags }: { tags: ErrorTrackingIssueTag[] }): JSX.Element | null {
    if (tags.length === 0) {
        return null
    }
    return (
        // The pane paints no background of its own on desktop, so this strip paints the one the sections
        // below it paint.
        <div className="flex shrink-0 flex-wrap items-center gap-1 border-b bg-surface-primary px-2 py-1.5">
            {tags.map((tag) => {
                const by = answeredBy(tag.source)
                // LemonTag renders a div, so it needs a tab stop: the tooltip holds the only copy of the
                // description and of who answered.
                return (
                    <Tooltip
                        key={tag.key}
                        title={
                            <div className="flex flex-col gap-1">
                                <span>{tag.description}</span>
                                {by ? <span className="font-semibold">{by}</span> : null}
                            </div>
                        }
                    >
                        <LemonTag tabIndex={0}>{tag.label}</LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}
