import { cn } from '@posthog/quill-primitives'

import { ActivitySubsteps } from '../ActivitySubsteps'
import type { ActivityProps } from '../activityTypes'
import { useActivityDisclosure } from '../useActivityDisclosure'
import { ThreadMarker } from './ThreadMarker'

/**
 * `Activity` in the quill skin: the header becomes a `ChatMarker` row, substeps and details its
 * collapsible body, and `children` stay visible under the row. Open state follows `Activity`: it
 * auto-expands while running when `autoExpand` is set and collapses once the step settles.
 */
export function QuillActivity({
    id,
    title,
    subtitle,
    status,
    icon,
    animate = true,
    showProgressIcon = false,
    failedIcon,
    substeps = [],
    details = null,
    children = null,
    autoExpand = true,
    onToggleDetails,
}: ActivityProps): JSX.Element {
    const hasDetails = substeps.length > 0 || !!details
    const { open, setOpen } = useActivityDisclosure({ autoExpand, hasDetails, status, onToggleDetails })

    const isRunning = status === 'in_progress'
    const body = hasDetails ? (
        <div className="flex min-w-0 flex-col gap-1 ps-5 text-muted-foreground" data-not-quill>
            {substeps.length > 0 && <ActivitySubsteps id={id} substeps={substeps} status={status} />}
            {details}
        </div>
    ) : undefined

    return (
        <div className="flex min-w-0 flex-col gap-1">
            <ThreadMarker
                icon={status === 'failed' && failedIcon ? failedIcon : icon}
                running={isRunning && animate}
                spinner={showProgressIcon}
                failed={status === 'failed'}
                body={body}
                open={open}
                onOpenChange={setOpen}
                className={cn(status === 'pending' && 'opacity-40')}
            >
                <span className="min-w-0 truncate font-medium">{title}</span>
                {subtitle && <span className="min-w-0 truncate text-muted-foreground">{subtitle}</span>}
            </ThreadMarker>
            {/* Product widgets (charts, tables, diffs) keep PostHog's own colours inside the quill thread. */}
            {children && (
                <div className="min-w-0 ps-5" data-not-quill>
                    {children}
                </div>
            )}
        </div>
    )
}
