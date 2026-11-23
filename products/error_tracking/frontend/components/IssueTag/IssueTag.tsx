import './IssueTag.scss'

import { forwardRef } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { ErrorTrackingIssueTagColor } from '~/queries/schema/schema-general'

type IssueTagProps = Omit<React.ComponentPropsWithoutRef<typeof LemonTag>, 'children' | 'type' | 'color'> & {
    label: string
    color: ErrorTrackingIssueTagColor | null | undefined
}

// Forwards the ref and props to LemonTag, so the tag can be a Tooltip trigger.
export const IssueTag = forwardRef<HTMLDivElement, IssueTagProps>(function IssueTag(
    { label, color, className, ...props },
    ref
): JSX.Element {
    return (
        <LemonTag ref={ref} className={cn(color && `IssueTag--${color}`, className)} {...props}>
            <span className="truncate">{label}</span>
        </LemonTag>
    )
})
