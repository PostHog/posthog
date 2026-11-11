import { useValues } from 'kea'
import { useEffect } from 'react'

import { userLogic } from 'scenes/userLogic'

import { wizardRunSidebarLogic } from './wizardRunSidebarLogic'

export function WizardRunsUnseenDot({
    projectId,
    onUnseenChange,
}: {
    projectId: string
    /** The dot is aria-hidden, so the trigger needs the state for its accessible name. */
    onUnseenChange: (hasUnseenRuns: boolean) => void
}): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { hasUnseenRuns } = useValues(wizardRunSidebarLogic({ projectId, userId: user?.id ?? 0 }))

    useEffect(() => {
        onUnseenChange(hasUnseenRuns)
        return () => onUnseenChange(false)
    }, [hasUnseenRuns, onUnseenChange])

    if (!hasUnseenRuns) {
        return null
    }
    return (
        <span
            aria-hidden
            className="absolute -top-0.5 -end-0.5 size-2 rounded-full bg-[var(--primary)] ring-2 ring-[var(--chrome)]"
        />
    )
}
