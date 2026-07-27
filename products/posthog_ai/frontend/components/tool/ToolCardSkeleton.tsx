import { Spinner } from '@posthog/lemon-ui'

/**
 * Eager, dependency-light placeholder shown while a tool renderer's lazy chunk loads. A single
 * Activity-style header line (registry icon + name + spinner, no body) — must not import the lazy
 * renderers, or it would defeat the code split it stands in for.
 */
export function ToolCardSkeleton({ icon, displayName }: { icon?: JSX.Element; displayName?: string }): JSX.Element {
    return (
        <div className="flex items-center select-none min-w-0 text-xs">
            <div className="flex items-center justify-center size-5 text-muted">{icon}</div>
            <div className="flex items-center gap-1 flex-1 min-w-0">
                <span className="text-muted truncate">{displayName ?? 'Tool'}</span>
                <Spinner className="size-3 shrink-0" />
            </div>
        </div>
    )
}
