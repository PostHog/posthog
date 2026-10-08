import { useLayoutEffect, useState } from 'react'

import type { ActivityStatus } from './activityTypes'

/**
 * Open state for an activity's details, shared by every skin. With `autoExpand`, details open while the
 * step runs and close once it settles; a reader's toggle holds until the status changes that rule.
 */
export function useActivityDisclosure({
    autoExpand,
    hasDetails,
    status,
    onToggleDetails,
}: {
    autoExpand: boolean
    hasDetails: boolean
    status: ActivityStatus
    onToggleDetails?: (expanded: boolean) => void
}): { open: boolean; setOpen: (open: boolean) => void } {
    const shouldExpand = autoExpand && hasDetails && status !== 'completed' && status !== 'failed'
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
