import { JSX, ReactNode } from 'react'

import { Icon } from '../primitives/icons'
import { LoadingIcon, StatusIndicators, ToolTitle } from '../primitives/toolCallUtils'

interface ToolRowProps {
    icon: Icon
    isLoading: boolean
    isFailed?: boolean
    wasCancelled?: boolean
    children: ReactNode
}

export function ToolRow({ icon, isLoading, isFailed, wasCancelled, children }: ToolRowProps): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2 py-0.5">
            <LoadingIcon icon={icon} isLoading={isLoading} />
            <ToolTitle>{children}</ToolTitle>
            <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
        </div>
    )
}
