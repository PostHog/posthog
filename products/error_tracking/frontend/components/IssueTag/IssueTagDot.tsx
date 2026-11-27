import './IssueTag.scss'

import { cn } from 'lib/utils/css-classes'

import type { ErrorTrackingIssueTagColor } from '~/queries/schema/schema-general'

export function IssueTagDot({
    color,
    className,
}: {
    color: ErrorTrackingIssueTagColor
    className?: string
}): JSX.Element {
    return <span aria-hidden className={cn('size-2.5 shrink-0 rounded-full', `IssueTagDot--${color}`, className)} />
}
