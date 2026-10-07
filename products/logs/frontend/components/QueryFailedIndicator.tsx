import { IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

/** Overlays a warning on a pane whose query failed. The parent must be `relative`. */
export function QueryFailedIndicator({ error, label }: { error: string | null; label: string }): JSX.Element | null {
    if (!error) {
        return null
    }
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span>Couldn't load {label}. Refresh to try again.</span>
                    <span className="text-xs opacity-75">{error}</span>
                </div>
            }
        >
            <span
                className="absolute top-2 right-2 z-10 flex items-center justify-center rounded bg-surface-primary border p-1 text-warning"
                aria-label={`Couldn't load ${label}`}
                role="img"
                data-attr="query-failed-indicator"
            >
                <IconWarning className="text-lg" />
            </span>
        </Tooltip>
    )
}
