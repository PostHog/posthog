import { type ReactNode } from 'react'

import { Activity } from './ActivityPrimitives'
import type { ActivityStatus } from './ActivityPrimitives'

/**
 * Progress / status card for the sandbox runtime — a thin adapter over the shared `Activity` used by
 * `SandboxProgressItem` and the status/substep thread items. (Tool calls render via the dedicated
 * `SandboxToolActivity` bridge, not this.)
 */
export function SandboxActivity({
    id,
    content,
    substeps,
    state,
    icon,
    animate = true,
    showCompletionIcon = true,
}: {
    id: string
    content: ReactNode
    substeps: string[]
    state: ActivityStatus
    icon?: ReactNode
    animate?: boolean
    showCompletionIcon?: boolean
}): JSX.Element {
    return (
        <Activity
            id={id}
            title={content}
            substeps={substeps}
            status={state}
            icon={icon}
            animate={animate}
            showCompletionIcon={showCompletionIcon}
        />
    )
}
