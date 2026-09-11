import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { percentage } from 'lib/utils/numbers'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { IngestionLimitBanner } from '../components/IngestionLimitBanner'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { formatCreditsRange } from '../utils/credits'
import { quotaBannerState } from '../utils/quotaProjection'
import { ScannerObservationsTable } from './components/ScannerObservationsTable'
import { ScannerOverview } from './components/ScannerOverview'
import { ScannerScoutCard } from './components/ScannerScoutCard'
import { replayScannerLogic } from './replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from './replayScannerSceneLogic'
import { scanDrought } from './scanDrought'
import { LIMIT_REACHED_TOOLTIP } from './scannerCopy'

const ObservationSearchTab = lazyWithRetry(() =>
    import('../search/ObservationSearchTab').then((module) => ({ default: module.ObservationSearchTab }))
)
const ScannerAlertsTab = lazyWithRetry(() =>
    import('./components/ScannerAlertsTab').then((module) => ({ default: module.ScannerAlertsTab }))
)
const ScannerBackfillsTab = lazyWithRetry(() =>
    import('./components/ScannerBackfillsTab').then((module) => ({ default: module.ScannerBackfillsTab }))
)
const ScannerCalibrationTab = lazyWithRetry(() =>
    import('./components/ScannerCalibrationTab').then((module) => ({ default: module.ScannerCalibrationTab }))
)
const ScannerConfigReadonly = lazyWithRetry(() =>
    import('./components/ScannerConfigReadonly').then((module) => ({ default: module.ScannerConfigReadonly }))
)
const ScannerRunTab = lazyWithRetry(() =>
    import('./components/ScannerRunTab').then((module) => ({ default: module.ScannerRunTab }))
)
const ScannerScoutsTab = lazyWithRetry(() =>
    import('./components/ScannerScoutsTab').then((module) => ({ default: module.ScannerScoutsTab }))
)

export const scene: SceneExport = {
    component: ReplayScannerSceneComponent,
    logic: replayScannerSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayScannerSceneComponent(): JSX.Element {
    const { scannerId, activeTab } = useValues(replayScannerSceneLogic)
    const { setActiveTab } = useActions(replayScannerSceneLogic)

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
                nameSuffix={
                    scanner.limit_reached ? (
                        <Tooltip title={LIMIT_REACHED_TOOLTIP}>
                            <LemonTag type="danger">Limit reached</LemonTag>
                        </Tooltip>
                    ) : undefined
                }
                description={scanner.description}
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        {activeTab !== ReplayScannerTab.Calibration && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSparkles />}
                                tooltip="Rate scanner results and apply PostHog AI config recommendations in the Calibration tab"
                                onClick={() => setActiveTab(ReplayScannerTab.Calibration)}
                                data-attr="replay-vision-open-calibration-tab"
                            >
                                Improve scanner
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            size="small"
                            to={urls.replayVisionScannerConfigure(scannerId)}
                            disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                            data-attr="vision-scanner-edit"
                            data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                        >
                            Edit scanner
                        </LemonButton>
                        <ReplayVisionFeedbackButton />
                    </>
                }
            />

            <IngestionLimitBanner />
            <QuotaBanner />
            <ScanDroughtBanner scannerId={scannerId} />

            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                data-attr="vision-scanner-tabs"
                tabs={[
                    {
                        key: ReplayScannerTab.Overview,
                        label: 'Overview',
                        content: (
                            <div className="flex flex-col gap-6">
                                <ScannerScoutCard scannerId={scannerId} scannerName={scanner.name || ''} />
                                <ScannerOverview scannerId={scannerId} />
                            </div>
                        ),
                    },
                    {
                        key: ReplayScannerTab.Observations,
                        label: 'Observations',
                        content: <ScannerObservationsTable scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Search,
                        label: 'Search',
                        content: <ObservationSearchTab scanner={scanner} />,
                    },
                    {
                        key: ReplayScannerTab.OnDemand,
                        label: 'On-demand',
                        content: <ScannerRunTab scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Backfills,
                        label: 'Backfills',
                        content: <ScannerBackfillsTab scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Configuration,
                        label: 'Configuration',
                        content: <ScannerConfigReadonly scanner={scanner} />,
                    },
                    {
                        key: ReplayScannerTab.Calibration,
                        label: 'Calibration',
                        content: <ScannerCalibrationTab scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Scouts,
                        label: (
                            <>
                                Scouts{' '}
                                <LemonTag type="completion" size="small" className="ml-1">
                                    Beta
                                </LemonTag>
                            </>
                        ),
                        content: <ScannerScoutsTab scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Alerts,
                        label: 'Alerts',
                        content: <ScannerAlertsTab scannerId={scannerId} />,
                    },
                ].map((tab) => ({
                    ...tab,
                    content: <Suspense fallback={<Spinner className="m-4" />}>{tab.content}</Suspense>,
                }))}
            />
        </SceneContent>
    )
}

// Assumes block-only overage policy; revisit when `usage_based` ships so we don't scare metered orgs.
function QuotaBanner(): JSX.Element | null {
    const { quota, onFreePlan } = useValues(visionQuotaLogic)
    const state = quotaBannerState(quota)
    if (!state.kind) {
        return null
    }
    return (
        <LemonBanner type="warning">
            {state.kind === 'exhausted'
                ? `${
                      onFreePlan ? 'Free credits used up' : 'Spend limit reached'
                  }: ${formatCreditsRange(state.quota.credits_used, state.quota.credit_limit ?? 0)}. New observations are paused until ${state.resetsOn}.`
                : onFreePlan
                  ? `You've used ${Math.round(state.quota.credits_used).toLocaleString('en-US')} of your ${Math.round(state.quota.credit_limit ?? 0).toLocaleString('en-US')} free credits this billing period. New observations will pause once they run out. Resets ${state.resetsOn}.`
                  : `You've used ${formatCreditsRange(state.quota.credits_used, state.quota.credit_limit ?? 0)} this billing period. New observations will pause once you hit the limit. Resets ${state.resetsOn}.`}
        </LemonBanner>
    )
}

// Silence after a config change reads as "the product is broken", so name the real cause: filters that
// match nothing, or sampling skipping the few sessions that do match.
function ScanDroughtBanner({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, observationStatsApi } = useValues(replayScannerLogic({ id: scannerId }))
    const { quota } = useValues(visionQuotaLogic)
    // An exhausted quota already explains the silence in its own banner above.
    if (!scanner || quotaBannerState(quota).kind === 'exhausted') {
        return null
    }
    const drought = scanDrought(scanner, observationStatsApi?.labels.version_markers ?? null, new Date())
    if (!drought) {
        return null
    }
    const samplingNote =
        drought.samplingRate < 1
            ? `, and sampling only scans ${percentage(drought.samplingRate)} of the sessions that do`
            : ''
    return (
        <LemonBanner
            type="warning"
            action={{ children: 'Review filters', to: urls.replayVisionScannerTriggers(scannerId) }}
        >
            {drought.everScanned
                ? `No sessions have been scanned since this scanner's configuration last changed, even though sweeps have run since. The filters may match no recordings${samplingNote}.`
                : `This scanner hasn't scanned any sessions yet, even though sweeps have run. The filters may match no recordings${samplingNote}.`}
        </LemonBanner>
    )
}

export default ReplayScannerSceneComponent
