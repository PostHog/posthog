import clsx from 'clsx'

import { LemonTag } from '@posthog/lemon-ui'

/**
 * A report's slug tags. With `onTagClick` each tag is a button that filters the inbox by it. The
 * click stops there, so a tag inside a card link does not also open the report.
 */
export function ReportTagList({
    tags,
    onTagClick,
    className,
}: {
    tags?: string[]
    onTagClick?: (tag: string) => void
    className?: string
}): JSX.Element | null {
    if (!tags || tags.length === 0) {
        return null
    }
    return (
        <div className={clsx('flex flex-wrap items-center gap-1', className)}>
            {tags.map((tag) => (
                <LemonTag
                    key={tag}
                    size="small"
                    type="muted"
                    className="font-mono"
                    title={onTagClick ? `Show reports tagged ${tag}` : undefined}
                    data-attr="inbox-report-tag"
                    onClick={
                        onTagClick
                            ? (event) => {
                                  event.preventDefault()
                                  event.stopPropagation()
                                  onTagClick(tag)
                              }
                            : undefined
                    }
                >
                    {tag}
                </LemonTag>
            ))}
        </div>
    )
}
