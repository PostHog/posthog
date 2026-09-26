import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import {
    DEFAULT_EXPERIMENT_TAB,
    type ExperimentTab,
    experimentSceneLogic,
} from 'scenes/experiments/experimentSceneLogic'
import { DistributionModal, DistributionTable } from 'scenes/experiments/ExperimentView/DistributionTable'
import { ExperimentWarningBanner } from 'scenes/experiments/ExperimentView/ExperimentWarningBanners'
import { LoadingState } from 'scenes/experiments/ExperimentView/LoadingState'
import { PageHeaderCustom } from 'scenes/experiments/ExperimentView/PageHeader'
import {
    ReleaseConditionsModal,
    ReleaseConditionsTable,
} from 'scenes/experiments/ExperimentView/ReleaseConditionsTable'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SidePanelTab } from '~/types'

import { LegacyExperimentInfo } from './LegacyExperimentInfo'
import { LegacyMetricsList } from './LegacyMetricsList'

const VariantsTab = (): JSX.Element => {
    return (
        <div className="deprecated-space-y-8 mt-2">
            <ReleaseConditionsTable />
            <DistributionTable />
        </div>
    )
}

/**
 * Read-only page for experiments whose metrics use the retired ExperimentTrendsQuery/ExperimentFunnelsQuery
 * format. Results are no longer calculated for them, so it lists the metrics and points to the migration.
 */
export function LegacyExperimentView(): JSX.Element {
    const { experimentLoading, experiment } = useValues(experimentLogic)
    const { activeTabKey } = useValues(experimentSceneLogic)
    const { setActiveTabKey } = useActions(experimentSceneLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const tabs: LemonTab<ExperimentTab>[] = [
        { key: 'metrics', label: 'Metrics', content: <LegacyMetricsList /> },
        { key: 'variants', label: 'Variants', content: <VariantsTab /> },
    ]

    return (
        <SceneContent>
            <PageHeaderCustom />
            {experimentLoading ? (
                <LoadingState />
            ) : (
                <>
                    <ExperimentWarningBanner />

                    <LemonBanner
                        type="warning"
                        className="mb-4"
                        action={{
                            children: 'Migrate with PostHog AI',
                            icon: <IconSparkles />,
                            // The "!" prefix submits the prompt without review, so keep user-editable text like the name out of it
                            onClick: () =>
                                openSidePanel(
                                    SidePanelTab.Max,
                                    `!Migrate experiment ${experiment.id} to the new experiment engine`
                                ),
                            'data-attr': 'legacy-experiment-migrate-with-ai',
                        }}
                    >
                        Results for legacy experiments are no longer available. If you still need them, migrate this
                        experiment to the new experiment engine with PostHog AI.
                    </LemonBanner>

                    {experiment.feature_flag?.id && (
                        <PendingChangeRequestBanner
                            resourceType="feature_flag"
                            resourceId={experiment.feature_flag.id}
                            context="experiment"
                        />
                    )}

                    <LegacyExperimentInfo />

                    <LemonTabs
                        // Fall back to the default tab if the active one isn't rendered here
                        activeKey={tabs.some((tab) => tab.key === activeTabKey) ? activeTabKey : DEFAULT_EXPERIMENT_TAB}
                        onChange={(key) => setActiveTabKey(key)}
                        sceneInset
                        tabs={tabs}
                    />

                    <DistributionModal />
                    <ReleaseConditionsModal />
                </>
            )}
        </SceneContent>
    )
}
