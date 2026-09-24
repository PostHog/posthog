import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
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
import { calibrationActivationLogic } from './calibrationActivationLogic'
import { ScannerObservationsTable } from './components/ScannerObservationsTable'
import { ScannerOverview } from './components/ScannerOverview'
import { replayScannerLogic } from './replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from './replayScannerSceneLogic'

const ScannerAlertsTab = lazyWithRetry(() =>
    import('./components/ScannerAlertsTab').then((module) => ({ default: module.ScannerAlertsTab }))
)
const ScannerCalibrationTab = lazyWithRetry(() =>
    import('./components/ScannerCalibrationTab').then((module) => ({ default: module.ScannerCalibrationTab }))
)
const ScannerScanTab = lazyWithRetry(() =>
    import('./components/ScannerScanTab').then((module) => ({ default: module.ScannerScanTab }))
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
    const { variant: activationVariant, neverRated } = useValues(calibrationActivationLogic({ scannerId }))
    // `neverRated` already requires results to rate. A viewer who cannot rate is not nudged either,
    // because rating needs editor access, so nudging without it is a dead end.
    const shouldNudgeCalibration = neverRated && !getReplayVisionEditDisabledReason(scanner?.user_access_level)

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
                                {activationVariant === 'prompt' && shouldNudgeCalibration && (
                                    <div className="border rounded p-4 bg-surface-primary flex flex-wrap items-center justify-between gap-3">
                                        <div>
                                            <h3 className="font-semibold text-base m-0">Teach this scanner</h3>
                                            <p className="text-muted text-sm m-0 mt-0.5">
                                                None of its results are rated yet. Mark a few right or wrong, and
                                                PostHog AI turns what you flag into config changes you can review.
                                            </p>
                                        </div>
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            icon={<IconSparkles />}
                                            onClick={() => setActiveTab(ReplayScannerTab.Calibration)}
                                            data-attr="vision-calibration-activation-prompt"
                                        >
                                            Rate results
                                        </LemonButton>
                                    </div>
                                )}
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
                        key: ReplayScannerTab.Run,
                        label: 'Run',
                        content: <ScannerScanTab scannerId={scannerId} />,
                    },
                    {
                        key: ReplayScannerTab.Calibration,
                        label:
                            activationVariant === 'badge' && shouldNudgeCalibration ? (
                                <>
                                    Calibration{' '}
                                    <LemonTag type="highlight" size="small" className="ml-1">
                                        Not rated
                                    </LemonTag>
                                </>
                            ) : (
                                'Calibration'
                            ),
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

export default ReplayScannerSceneComponent
