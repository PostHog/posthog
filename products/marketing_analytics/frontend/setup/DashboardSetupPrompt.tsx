import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { DashboardSetupPromptKind, dashboardSetupPromptsLogic } from './dashboardSetupPromptsLogic'

export function DashboardSetupPrompt({
    kind,
    children,
}: {
    kind: DashboardSetupPromptKind
    children: (dismissButton: ReactNode) => ReactNode
}): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const logic = dashboardSetupPromptsLogic({ projectId: currentTeamId ?? -1, userId: user?.uuid })
    const { dismissed } = useValues(logic)
    const { dismiss } = useActions(logic)

    if (!currentTeamId || dismissed[kind]) {
        return null
    }

    return (
        <div data-attr={`marketing-dashboard-${kind}-prompt`}>
            {children(
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconX />}
                    aria-label={
                        kind === 'sources' ? 'Dismiss source suggestions' : 'Dismiss conversion recommendations'
                    }
                    tooltip="Dismiss"
                    onClick={() => dismiss(kind)}
                    data-attr={`marketing-dashboard-dismiss-${kind}`}
                />
            )}
        </div>
    )
}
