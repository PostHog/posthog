import { useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { wizardRunSidebarLogic } from './wizardRunSidebarLogic'

export function WizardRunsUnseenDot({ projectId }: { projectId: string }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { hasUnseenRuns } = useValues(wizardRunSidebarLogic({ projectId, userId: user?.id ?? 0 }))
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
