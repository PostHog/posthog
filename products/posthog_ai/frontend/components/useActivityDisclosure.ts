import { useLayoutEffect, useState } from 'react'

import type { ActivityStatus } from './activityTypes'

/**
 * Open state for an activity's details, shared by every skin. With `autoExpand`, details open while the
 * step runs and close once it settles; `defaultOpen` replaces that rule. A reader's toggle holds until the
 * rule's result changes.
 */
export function useActivityDisclosure({
    autoExpand,
    defaultOpen,
    hasDetails,
    status,
    onToggleDetails,
}: {
    autoExpand: boolean
    defaultOpen?: boolean
    hasDetails: boolean
    status: ActivityStatus
    onToggleDetails?: (expanded: boolean) => void
}): { open: boolean; setOpen: (open: boolean) => void } {
    const shouldExpand = hasDetails && (defaultOpen ?? (autoExpand && status !== 'completed' && status !== 'failed'))
    const [open, setOpenState] = useState(shouldExpand)
    useLayoutEffect(() => {
        setOpenState(shouldExpand)
    }, [shouldExpand])
    return {
        open,
        setOpen: (next) => {
            onToggleDetails?.(next)
            setOpenState(next)
        },
    }
}
