import { useActions, useValues } from 'kea'
import { Suspense, useEffect } from 'react'

import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { SceneExport } from 'scenes/sceneTypes'

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
import { replayScannerLogic } from './replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from './replayScannerSceneLogic'
import { scannerEditUrl } from './scannerEditorSceneLogic'

const ScannerAlertsTab = lazyWithRetry(() =>
    import('./components/ScannerAlertsTab').then((module) => ({ default: module.ScannerAlertsTab }))
)
const ScannerScanTab = lazyWithRetry(() =>
    import('./components/ScannerScanTab').then((module) => ({ default: module.ScannerScanTab }))
)
const VariantsTab = lazyWithRetry(() =>
    import('./components/variants/VariantsTab').then((module) => ({ default: module.VariantsTab }))
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
    const { scannerId, activeTab, defaultTab } = useValues(replayScannerSceneLogic)
    const { setActiveTab, setDefaultTab } = useActions(replayScannerSceneLogic)

    const scannerLogic = replayScannerLogic({ id: scannerId })
    useAttachedLogic(scannerLogic, replayScannerSceneLogic)

    const { scanner, scannerLoading } = useValues(scannerLogic)
    const experimentScanners = useFeatureFlag('VISION_EXPERIMENT_SCANNER')
    const isExperimentScanner = experimentScanners && scanner?.scanner_type === 'experiment'
    const loadedScannerId = scanner?.id ?? null

    // The scene logic can't see the scanner's type, so the page tells it which tab this scanner lands on.
    useEffect(() => {
        if (loadedScannerId) {
            setDefaultTab(isExperimentScanner ? ReplayScannerTab.Variants : ReplayScannerTab.Overview)
        }
    }, [loadedScannerId, isExperimentScanner, setDefaultTab])

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
                        <LemonButton
                            type="primary"
                            size="small"
                            to={scannerEditUrl(scannerId, activeTab === defaultTab ? null : activeTab)}
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

            <LemonTabs
                // Only an experiment scanner has a Variants tab, so a stale ?tab=variants falls back.
                activeKey={
                    activeTab === ReplayScannerTab.Variants && !isExperimentScanner
                        ? ReplayScannerTab.Overview
                        : activeTab
                }
                onChange={setActiveTab}
                data-attr="vision-scanner-tabs"
                tabs={[
                    {
                        key: ReplayScannerTab.Overview,
                        label: 'Overview',
                        content: <ScannerOverview scannerId={scannerId} />,
                    },
                    ...(isExperimentScanner
                        ? [
                              {
                                  key: ReplayScannerTab.Variants,
                                  label: 'Variants',
                                  content: <VariantsTab scannerId={scannerId} />,
                              },
                          ]
                        : []),
                    {
                        key: ReplayScannerTab.Observations,
                        label: 'Observations',
                        content: <ScannerObservationsTable scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Run,
                        label: 'Run',
                        content: <ScannerScanTab scannerId={scannerId} />,
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

export default ReplayScannerSceneComponent
