import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { ProductKey } from '@posthog/query-frontend/schema/schema-general'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { dayjs } from 'lib/dayjs'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
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

    const { scanner, scannerLoading, togglingEnabled } = useValues(scannerLogic)
    const { toggleEnabled } = useActions(scannerLogic)

    const handleToggleEnabledClick = (): void => {
        if (!scanner) {
            return
        }
        LemonDialog.open({
            title: scanner.enabled ? 'Disable scanner?' : 'Enable scanner?',
            description: scanner.enabled
                ? 'This will stop the scanner from analyzing new session recordings. Are you sure?'
                : 'The scanner will begin analyzing new session recordings that match its triggers',
            primaryButton: {
                children: scanner.enabled ? 'Disable' : 'Enable',
                status: scanner.enabled ? 'danger' : 'default',
                onClick: () => toggleEnabled(),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

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
                    </>
                }
            />

            <QuotaBanner />

            <div className="w-full max-w-xs">
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonSwitch
                        checked={scanner.enabled}
                        onChange={handleToggleEnabledClick}
                        loading={togglingEnabled}
                        label="Enable scanner"
                        bordered
                        fullWidth
                        data-attr="vision-scanner-toggle-enabled"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    />
                </AccessControlAction>
            </div>

            <ScannerOverview scannerId={scannerId} />

            <div className="flex flex-col gap-2">
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
                <SummarizerMaxChat scannerId={scannerId} />
                <ScannerObservationsTable scannerId={scannerId} />
            </div>
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
