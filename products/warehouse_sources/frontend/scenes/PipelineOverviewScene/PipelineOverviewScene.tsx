import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ManagedSourcesTable } from 'products/data_warehouse/frontend/shared/components/ManagedSourcesTable'

import { PipelineHealth } from './PipelineHealth'
import type { PipelineStatsWindow } from './pipelineOverviewSceneLogic'
import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'
import { PipelineStatTiles } from './PipelineStatTiles'
import { RecentRuns } from './RecentRuns'
import { RowsByDestination } from './RowsByDestination'

export const scene: SceneExport = {
    component: PipelineOverviewScene,
    logic: pipelineOverviewSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function PipelineOverviewScene(): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { window, jobStatsLoading, hasIssues, lastUpdatedAt } = useValues(pipelineOverviewSceneLogic)
    const { setWindow, refresh } = useActions(pipelineOverviewSceneLogic)

    // Wait for the flags to land before refusing. Rendering NotFound first and the scene a beat
    // later reads as a broken page to anyone who does have the flag.
    if (receivedFeatureFlags && !featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION]) {
        return <NotFound object="page" caption="ETL isn't available for this project yet." />
    }

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name="ETL"
                description="Every source you import from and every destination you write to, with the health of each."
                resourceType={{ type: 'data_pipeline' }}
                actions={
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={refresh}
                            loading={jobStatsLoading}
                            data-attr="etl-refresh"
                        >
                            Refresh
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlusSmall />}
                            to={urls.dataPipelinesNew('source')}
                            data-attr="etl-new-source"
                        >
                            New source
                        </LemonButton>
                    </div>
                }
            />

            <PipelineStatTiles />
            {lastUpdatedAt ? (
                <div className="-mt-1 text-xs text-muted">
                    Updated <TZLabel time={lastUpdatedAt} />, and every 30 seconds while this page is open
                </div>
            ) : null}

            <SceneDivider />

            {/* Hidden entirely when everything is healthy: an empty problem list is not worth the
                vertical space, and its absence already says there is nothing wrong. */}
            {hasIssues ? (
                <>
                    <SceneSection title="Needs attention" description="Tables and sources that have stopped syncing.">
                        <PipelineHealth />
                    </SceneSection>

                    <SceneDivider />
                </>
            ) : null}

            <SceneSection title="Rows synced by destination">
                <RowsByDestination />
            </SceneSection>

            <SceneDivider />
            <SceneSection
                title="Runs"
                description="Every sync in this window, newest first. Runs in flight appear as they start."
                actions={
                    <LemonSelect<PipelineStatsWindow>
                        size="small"
                        value={window}
                        onChange={setWindow}
                        data-attr="etl-window"
                        options={[
                            { value: 1, label: 'Last 24 hours' },
                            { value: 7, label: 'Last 7 days' },
                            { value: 30, label: 'Last 30 days' },
                        ]}
                    />
                }
            >
                <RecentRuns />
            </SceneSection>

            <SceneDivider />

            <SceneSection title="Synced sources" description="Sources PostHog imports on a schedule.">
                <ManagedSourcesTable />
            </SceneSection>

            <SceneDivider />

            <SceneSection
                title="Sources and destinations"
                description="Connect a source, and choose where its tables are written."
            >
                <div className="flex flex-wrap gap-2">
                    <LemonButton type="secondary" size="small" to={urls.sources()} data-attr="etl-sources">
                        Manage sources
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.warehouseDestinations()}
                        data-attr="etl-destinations"
                    >
                        Manage destinations
                    </LemonButton>
                </div>
            </SceneSection>
        </SceneContent>
    )
}
