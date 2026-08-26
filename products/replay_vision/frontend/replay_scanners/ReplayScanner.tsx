import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { percentage } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { IngestionLimitBanner } from '../components/IngestionLimitBanner'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { ObservationSearchTab } from '../search/ObservationSearchTab'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { formatCreditsRange } from '../utils/credits'
import { quotaBannerState } from '../utils/quotaProjection'
import { ScannerBackfillsTab } from './components/ScannerBackfillsTab'
import { ScannerCalibrationTab } from './components/ScannerCalibrationTab'
import { ScannerConfigReadonly } from './components/ScannerConfigReadonly'
import { ScannerDigestCard } from './components/ScannerDigestCard'
import { ScannerObservationsTable } from './components/ScannerObservationsTable'
import { ScannerOverview } from './components/ScannerOverview'
import { ScannerRunTab } from './components/ScannerRunTab'
import { ScannerScoutCard } from './components/ScannerScoutCard'
import { ScannerScoutsTab } from './components/ScannerScoutsTab'
import { VisionActionsTab } from './components/VisionActionsTab'
import { replayScannerLogic } from './replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from './replayScannerSceneLogic'
import { scanDrought } from './scanDrought'
import { LIMIT_REACHED_TOOLTIP } from './scannerCopy'

export const scene: SceneExport = {
    component: ReplayScannerSceneComponent,
    logic: replayScannerSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayScannerSceneComponent(): JSX.Element {
    const { scannerId, activeTab } = useValues(replayScannerSceneLogic)
    const { setActiveTab } = useActions(replayScannerSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const scoutDigests = !!featureFlags[FEATURE_FLAGS.REPLAY_VISION_SCOUT_DIGESTS]
    const visibleTabs = Object.values(ReplayScannerTab).filter((tab) => scoutDigests || tab !== ReplayScannerTab.Scouts)

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
                // The scene logic keeps a `?tab=scouts` URL off this tab when the flag is off. This
                // covers the other way in: a flag that flips off while the tab is already open.
                activeKey={visibleTabs.includes(activeTab) ? activeTab : ReplayScannerTab.Overview}
                onChange={setActiveTab}
                data-attr="vision-scanner-tabs"
                tabs={[
                    {
                        key: ReplayScannerTab.Overview,
                        label: 'Overview',
                        content: (
                            <div className="flex flex-col gap-6">
                                {scoutDigests ? (
                                    <ScannerScoutCard scannerId={scannerId} scannerName={scanner.name || ''} />
                                ) : (
                                    <ScannerDigestCard scannerId={scannerId} scannerName={scanner.name || ''} />
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
                        key: ReplayScannerTab.Search,
                        label: 'Search',
                        content: <ObservationSearchTab scannerId={scannerId} />,
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
                    ...(scoutDigests
                        ? [
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
                          ]
                        : []),
                    {
                        key: ReplayScannerTab.Actions,
                        // Digests moved to their own Scouts tab, leaving this one to alerts alone.
                        label: scoutDigests ? 'Alerts' : 'Digests and alerts',
                        content: (
                            <VisionActionsTab
                                scannerId={scannerId}
                                scannerUserAccessLevel={scanner.user_access_level}
                            />
                        ),
                    },
                ]}
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
