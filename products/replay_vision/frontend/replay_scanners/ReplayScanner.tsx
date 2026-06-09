import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
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
import { ScannerConfigReadonly } from './components/ScannerConfigReadonly'
import { ScannerObservationsTable } from './components/ScannerObservationsTable'
import { ScannerOverview } from './components/ScannerOverview'
import { SummarizerMaxChat } from './components/SummarizerMaxChat'
import { replayScannerLogic } from './replayScannerLogic'
import { replayScannerSceneLogic } from './replayScannerSceneLogic'

export const scene: SceneExport = {
    component: ReplayScannerSceneComponent,
    logic: replayScannerSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayScannerSceneComponent(): JSX.Element {
    const { scannerId } = useValues(replayScannerSceneLogic)

    const scannerLogic = replayScannerLogic({ id: scannerId })
    useAttachedLogic(scannerLogic, replayScannerSceneLogic)

    const { scanner, scannerLoading } = useValues(scannerLogic)
    const { deleteScanner } = useActions(scannerLogic)

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
                        <ReplayVisionFeedbackButton />
                        <More
                            size="small"
                            overlay={
                                <LemonButton
                                    status="danger"
                                    fullWidth
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: `Delete "${scanner.name || 'Untitled scanner'}"?`,
                                            description: 'This cannot be undone.',
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => deleteScanner(),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }
                                    data-attr="vision-scanner-delete"
                                    data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                                >
                                    Delete
                                </LemonButton>
                            }
                        />
                    </>
                }
            />

            <QuotaBanner />

            <ScannerOverview scannerId={scannerId} />

            <LemonCollapse
                panels={[
                    {
                        key: 'configuration',
                        header: 'Configuration',
                        content: <ScannerConfigReadonly scanner={scanner} />,
                        dataAttr: 'vision-scanner-config-expand',
                    },
                ]}
            />
            <div className="flex items-center justify-end">
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        to={urls.replayVisionScannerConfigure(scannerId)}
                        data-attr="vision-scanner-edit"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    >
                        Edit scanner
                    </LemonButton>
                </AccessControlAction>
            </div>

            <SummarizerMaxChat scannerId={scannerId} />
            <ScannerObservationsTable scannerId={scannerId} />
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
