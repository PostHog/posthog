import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { QUOTA_WARN_THRESHOLD } from '../utils/quotaProjection'
import { ObservationSearchMaxChat } from './components/ObservationSearchMaxChat'
import { ScannerConfigReadonly } from './components/ScannerConfigReadonly'
import { ScannerObservationsTable } from './components/ScannerObservationsTable'
import { ScannerOverview } from './components/ScannerOverview'
import { ScannerQualityTab } from './components/ScannerQualityTab'
import { ScannerRunTab } from './components/ScannerRunTab'
import { SummarizerMaxChat } from './components/SummarizerMaxChat'
import { VisionActionsTab } from './components/VisionActionsTab'
import { replayScannerLogic } from './replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from './replayScannerSceneLogic'

export const scene: SceneExport = {
    component: ReplayScannerSceneComponent,
    logic: replayScannerSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayScannerSceneComponent(): JSX.Element {
    const { scannerId, activeTab } = useValues(replayScannerSceneLogic)
    const { setActiveTab } = useActions(replayScannerSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const actionsTabEnabled = !!featureFlags[FEATURE_FLAGS.REPLAY_VISION_ACTIONS]
    const qualityTabEnabled = !!featureFlags[FEATURE_FLAGS.REPLAY_VISION_QUALITY]

    const scannerLogic = replayScannerLogic({ id: scannerId })
    useAttachedLogic(scannerLogic, replayScannerSceneLogic)

    const { scanner, scannerLoading } = useValues(scannerLogic)

    if (scannerLoading || !scanner) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={scanner.name || 'Untitled scanner'}
                description={scanner.description}
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        {qualityTabEnabled && activeTab !== ReplayScannerTab.Quality && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSparkles />}
                                tooltip="Rate scanner results and apply AI prompt recommendations in the Quality tab"
                                onClick={() => setActiveTab(ReplayScannerTab.Quality)}
                                data-attr="replay-vision-open-quality-tab"
                            >
                                Improve scanner prompt
                            </LemonButton>
                        )}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                size="small"
                                to={urls.replayVisionScannerConfigure(scannerId)}
                                data-attr="vision-scanner-edit"
                                data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                            >
                                Edit scanner
                            </LemonButton>
                        </AccessControlAction>
                        <ReplayVisionFeedbackButton />
                    </>
                }
            />

            <QuotaBanner />

            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                data-attr="vision-scanner-tabs"
                tabs={[
                    {
                        key: ReplayScannerTab.Observations,
                        label: 'Observations',
                        content: (
                            <div className="flex flex-col gap-6">
                                <ScannerOverview scannerId={scannerId} />
                                <div className="flex flex-col gap-2">
                                    <SummarizerMaxChat scannerId={scannerId} />
                                    <ObservationSearchMaxChat scannerId={scannerId} />
                                    <ScannerObservationsTable scannerId={scannerId} />
                                </div>
                            </div>
                        ),
                    },
                    qualityTabEnabled && {
                        key: ReplayScannerTab.Quality,
                        label: 'Quality',
                        content: <ScannerQualityTab scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.OnDemand,
                        label: 'On-demand',
                        content: <ScannerRunTab scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Configuration,
                        label: 'Configuration',
                        content: <ScannerConfigReadonly scanner={scanner} />,
                    },
                    actionsTabEnabled && {
                        key: ReplayScannerTab.Actions,
                        label: 'Actions',
                        content: <VisionActionsTab scannerId={scannerId} />,
                    },
                ]}
            />
        </SceneContent>
    )
}

// Assumes block-only overage policy; revisit when `usage_based` ships so we don't scare metered orgs.
function QuotaBanner(): JSX.Element | null {
    const { quota } = useValues(visionQuotaLogic)
    if (!quota || quota.monthly_quota <= 0) {
        return null
    }
    const resetsOn = dayjs(quota.period_end).format('MMMM D')
    if (quota.exhausted) {
        return (
            <LemonBanner type="warning">
                Monthly observation quota reached ({quota.usage_this_month.toLocaleString()} /{' '}
                {quota.monthly_quota.toLocaleString()}). New observations are paused until {resetsOn}.
            </LemonBanner>
        )
    }
    if (quota.usage_this_month / quota.monthly_quota >= QUOTA_WARN_THRESHOLD) {
        return (
            <LemonBanner type="warning">
                {quota.usage_this_month.toLocaleString()} of {quota.monthly_quota.toLocaleString()} monthly observations
                used. New observations will pause once you hit the cap. Resets {resetsOn}.
            </LemonBanner>
        )
    }
    return null
}

export default ReplayScannerSceneComponent
