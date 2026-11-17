import { useActions, useValues } from 'kea'

import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { homeDashboardChoiceLogic } from './homeDashboardChoiceLogic'
import { HomeDashboardStarterModal } from './HomeDashboardStarterModal'

/** The dialogs that change which dashboard the product analytics Home shows. */
export function HomeDashboardModals(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { isOpen, dashboardChoiceView } = useValues(
        sceneDashboardChoiceModalLogic({ scene: Scene.ProductAnalyticsHomeTab })
    )
    const { dashboardCreationLoading } = useValues(homeDashboardChoiceLogic)
    const {
        closeSceneDashboardChoiceModal,
        showDashboardPicker,
        copyPostHogHome,
        createHomeDashboardWithAI,
        restorePostHogHome,
    } = useActions(homeDashboardChoiceLogic)

    return (
        <>
            <HomeDashboardStarterModal
                isOpen={isOpen && dashboardChoiceView === 'starter'}
                onClose={closeSceneDashboardChoiceModal}
                onCopyPostHogHome={copyPostHogHome}
                onTalkToAI={createHomeDashboardWithAI}
                onChooseExisting={showDashboardPicker}
                hasCustomDashboard={!!currentTeam?.home_tab_dashboard}
                onRestorePostHogHome={restorePostHogHome}
                restoringPostHogHome={currentTeamLoading}
                creatingWithAI={dashboardCreationLoading}
                aiDisabledReason={
                    !dataProcessingAccepted &&
                    (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')
                }
            />
            <SceneDashboardChoiceModal scene={Scene.ProductAnalyticsHomeTab} />
        </>
    )
}
