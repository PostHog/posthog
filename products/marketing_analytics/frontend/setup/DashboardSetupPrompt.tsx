import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { DashboardSetupPromptKind, dashboardSetupPromptsLogic } from './dashboardSetupPromptsLogic'

export function DashboardSetupPrompt({
    kind,
    children,
    dismissible = true,
}: {
    kind: DashboardSetupPromptKind
    dismissible?: boolean
    children: (dismissButton: ReactNode) => ReactNode
}): JSX.Element | null {
    const { setupEnabled } = useValues(marketingAnalyticsLogic)
    const canDismiss = setupEnabled && dismissible
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const logic = dashboardSetupPromptsLogic({ projectId: currentTeamId ?? -1, userId: user?.uuid })
    const { dismissed } = useValues(logic)
    const { dismiss } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!currentTeamId || (canDismiss && dismissed[kind])) {
        return null
    }

    return (
        <div data-attr={`marketing-dashboard-${kind}-prompt`}>
            {children(
                !canDismiss ? null : todayRailNav ? (
                    <Button
                        size="icon"
                        aria-label={
                            kind === 'sources' ? 'Dismiss source suggestions' : 'Dismiss conversion recommendations'
                        }
                        tooltip="Dismiss"
                        onClick={() => dismiss(kind)}
                        data-attr={`marketing-dashboard-dismiss-${kind}`}
                    >
                        <IconX />
                    </Button>
                ) : (
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
                )
            )}
        </div>
    )
}
