import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
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

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

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
    const { experimentLoading, experiment, migrateLegacyExperimentLoading } = useValues(experimentLogic)
    const { migrateLegacyExperiment } = useActions(experimentLogic)
    const { activeTabKey } = useValues(experimentSceneLogic)
    const { setActiveTabKey } = useActions(experimentSceneLogic)

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
                            children: 'Migrate experiment',
                            onClick: () => migrateLegacyExperiment(),
                            loading: migrateLegacyExperimentLoading,
                            disabledReason: getAccessControlDisabledReason(
                                AccessControlResourceType.Experiment,
                                AccessControlLevel.Editor,
                                experiment.user_access_level
                            ),
                            // pinned: click analytics for this button key on this data-attr, so renaming it breaks them
                            'data-attr': 'legacy-experiment-migrate-with-ai',
                        }}
                    >
                        Results for legacy experiments are no longer available. To see results, migrate this experiment
                        to the new experiment engine. This creates a copy that uses the same feature flag, so users keep
                        their variant.
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
