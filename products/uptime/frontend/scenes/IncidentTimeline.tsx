import { IconCheckCircle, IconEye, IconNotification, IconSearch, IconTarget, IconWrench } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import { IncidentUpdate, IncidentUpdateKeyword } from './uptimeSceneLogic'

const KEYWORD_LABEL: Record<IncidentUpdateKeyword, string> = {
    investigating: 'Investigating',
    identified: 'Identified',
    fixing: 'Fixing',
    monitoring: 'Monitoring fix',
    resolved: 'Resolved',
    update: 'Update',
}

// Pairs of (background tint, foreground colour) for the timeline dot. Kept as tailwind tokens
// so they stay in sync with the rest of the design system.
const KEYWORD_DOT_CLASS: Record<IncidentUpdateKeyword, string> = {
    investigating: 'bg-warning-highlight text-warning border border-warning',
    identified: 'bg-danger-highlight text-danger border border-danger',
    fixing: 'bg-primary-highlight text-primary border border-primary',
    monitoring: 'bg-accent-highlight-light text-accent border border-accent',
    resolved: 'bg-success-highlight text-success border border-success',
    update: 'bg-surface-secondary text-secondary border border-border',
}

const KEYWORD_ICON: Record<IncidentUpdateKeyword, JSX.Element> = {
    investigating: <IconSearch />,
    identified: <IconTarget />,
    fixing: <IconWrench />,
    monitoring: <IconEye />,
    resolved: <IconCheckCircle />,
    update: <IconNotification />,
}

const KEYWORD_TAG_TYPE: Record<
    IncidentUpdateKeyword,
    'warning' | 'danger' | 'primary' | 'completion' | 'success' | 'default'
> = {
    investigating: 'warning',
    identified: 'danger',
    fixing: 'primary',
    monitoring: 'completion',
    resolved: 'success',
    update: 'default',
}

export function IncidentKeywordTag({ keyword }: { keyword: IncidentUpdateKeyword }): JSX.Element {
    return (
        <LemonTag type={KEYWORD_TAG_TYPE[keyword]} size="small" className="uppercase tracking-wide">
            {KEYWORD_LABEL[keyword]}
        </LemonTag>
    )
}

interface IncidentTimelineProps {
    updates: IncidentUpdate[]
    /** If set, only render the first N entries — useful inside compact tiles. */
    limit?: number
    /** When true, render a "+N earlier" hint below the cropped list. */
    showCountHint?: boolean
    className?: string
}

export function IncidentTimeline({
    updates,
    limit,
    showCountHint = true,
    className,
}: IncidentTimelineProps): JSX.Element | null {
    if (!updates.length) {
        return null
    }
    const visible = typeof limit === 'number' ? updates.slice(0, limit) : updates
    const hiddenCount = updates.length - visible.length

    return (
        <div className={cn('flex flex-col', className)}>
            {visible.map((update, idx) => {
                const isLast = idx === visible.length - 1 && hiddenCount === 0
                return (
                    <div key={update.id} className="flex gap-2.5">
                        <div className="flex flex-col items-center">
                            <div
                                className={cn(
                                    'flex items-center justify-center w-6 h-6 rounded-full shrink-0',
                                    KEYWORD_DOT_CLASS[update.keyword]
                                )}
                                aria-hidden
                            >
                                <span className="text-sm leading-none">{KEYWORD_ICON[update.keyword]}</span>
                            </div>
                            {!isLast && <div className="flex-1 w-px bg-border my-1 min-h-2" />}
                        </div>
                        <div className={cn('flex-1 pb-3', isLast && 'pb-0')}>
                            <div className="flex items-center gap-2 flex-wrap">
                                <IncidentKeywordTag keyword={update.keyword} />
                                <span
                                    className="text-[11px] text-secondary"
                                    title={dayjs(update.posted_at).format('YYYY-MM-DD HH:mm:ss Z')}
                                >
                                    {dayjs(update.posted_at).fromNow()}
                                </span>
                            </div>
                            <div className="mt-1 text-xs whitespace-pre-wrap">{update.message}</div>
                        </div>
                    </div>
                )
            })}
            {hiddenCount > 0 && showCountHint && (
                <div className="text-[11px] text-secondary pl-8">
                    +{hiddenCount} earlier {hiddenCount === 1 ? 'update' : 'updates'}
                </div>
            )}
        </div>
    )
}
