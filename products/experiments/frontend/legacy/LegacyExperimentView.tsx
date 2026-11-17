import { useActions, useValues } from 'kea'

import { IconCorrelationAnalysis } from '@posthog/icons'
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
import { Hypothesis } from 'scenes/experiments/ExperimentView/Hypothesis'
import { LoadingState } from 'scenes/experiments/ExperimentView/LoadingState'
import { PageHeaderCustom } from 'scenes/experiments/ExperimentView/PageHeader'
import {
    ReleaseConditionsModal,
    ReleaseConditionsTable,
} from 'scenes/experiments/ExperimentView/ReleaseConditionsTable'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ExperimentMetaBar } from 'products/experiments/frontend/components/ExperimentMetaBar'

import { LegacyMetricsList } from './LegacyMetricsList'

const MetricsTab = (): JSX.Element => {
    return (
        <>
            <div className="w-full mb-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Hypothesis />
                <div className="h-full border border-primary rounded bg-[var(--color-bg-table)] px-3 py-2.5 flex flex-col gap-3">
                    <span className="metric-cell-header font-bold">Exposures</span>
                    <div className="flex-1 flex flex-col items-center justify-center gap-2 py-6 text-center">
                        <IconCorrelationAnalysis className="text-3xl text-tertiary" />
                        <p className="m-0 text-sm text-balance text-tertiary">
                            Exposures aren't calculated for legacy experiments. Migrate this experiment to see exposures
                            and results.
                        </p>
                    </div>
                </div>
            </div>
            <LegacyMetricsList />
        </>
    )
}

const VariantsTab = (): JSX.Element => {
    return (
        <div className="deprecated-space-y-8 mt-2">
            <ReleaseConditionsTable />
            <DistributionTable />
        </div>
    )
}

/**
 * Page for experiments whose metrics use the retired ExperimentTrendsQuery/ExperimentFunnelsQuery format. It keeps
 * the layout of the current experiment page, but results and exposures are no longer calculated for them, so it lists
 * the metrics, locks the analysis settings and points to the migration.
 */
export function LegacyExperimentView(): JSX.Element {
    const { experimentLoading, experiment, migrateLegacyExperimentLoading } = useValues(experimentLogic)
    const { migrateLegacyExperiment } = useActions(experimentLogic)
    const { activeTabKey } = useValues(experimentSceneLogic)
    const { setActiveTabKey } = useActions(experimentSceneLogic)

    const tabs: LemonTab<ExperimentTab>[] = [
        { key: 'metrics', label: 'Metrics', content: <MetricsTab /> },
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

                    <ExperimentMetaBar />

                    <LemonTabs
                        // Fall back to the default tab if the active one isn't rendered here
                        activeKey={tabs.some((tab) => tab.key === activeTabKey) ? activeTabKey : DEFAULT_EXPERIMENT_TAB}
                        onChange={(key) => setActiveTabKey(key)}
                        className="mt-4"
                        sceneInset
                        tabs={tabs.map((tab) =>
                            'content' in tab
                                ? {
                                      ...tab,
                                      content: <div className="w-full max-w-[1400px] mx-auto">{tab.content}</div>,
                                  }
                                : tab
                        )}
                    />

                    <DistributionModal />
                    <ReleaseConditionsModal />
                </>
            )}
        </SceneContent>
    )
}
