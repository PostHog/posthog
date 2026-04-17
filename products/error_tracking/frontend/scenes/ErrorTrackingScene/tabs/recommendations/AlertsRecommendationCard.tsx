import { BindLogic, useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AlertWizard } from 'scenes/hog-functions/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
} from 'scenes/hog-functions/AlertWizard/alertWizardLogic'
import { urls } from 'scenes/urls'

import { HogFunctionSubTemplateIdType } from '~/types'

import {
    ERROR_TRACKING_DESTINATIONS,
    ERROR_TRACKING_SUB_TEMPLATE_IDS,
    ERROR_TRACKING_TRIGGERS,
} from '../../../ErrorTrackingConfigurationScene/alerting/alertWizardConfig'
import { recommendationsTabLogic } from './recommendationsTabLogic'
import { ALERT_RECOMMENDATION_INFO, AlertsRecommendation } from './types'

export function AlertsRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: AlertsRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { dismissRecommendation, restoreRecommendation, refreshRecommendation } = useActions(recommendationsTabLogic)
    const alerts = recommendation.meta.alerts ?? []
    const canRefresh = !recommendation.next_refresh_at || new Date(recommendation.next_refresh_at) <= new Date()
    const [openTriggerKey, setOpenTriggerKey] = useState<HogFunctionSubTemplateIdType | null>(null)

    if (alerts.length === 0) {
        return null
    }

    const enabledCount = alerts.filter((a) => a.enabled).length

    return (
        <div className="border rounded-lg bg-surface-primary p-4">
            <div className="flex items-center justify-between mb-1">
                <h3 className="font-semibold text-sm m-0">Alert coverage</h3>
                <div className="flex items-center gap-2">
                    <span className="text-xs text-muted">
                        {enabledCount} / {alerts.length} configured
                    </span>
                    <div className="w-20 h-1.5 bg-border rounded-full">
                        <div
                            className="h-1.5 bg-success rounded-full"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: `${(enabledCount / alerts.length) * 100}%` }}
                        />
                    </div>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconRefresh />}
                        onClick={() => refreshRecommendation(recommendation.id)}
                        disabledReason={!canRefresh ? 'Too early to refresh' : undefined}
                        tooltip="Refresh this recommendation"
                    />
                    {dismissed ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => restoreRecommendation(recommendation.id)}
                        >
                            Restore
                        </LemonButton>
                    ) : (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            onClick={() => dismissRecommendation(recommendation.id)}
                            tooltip="Dismiss this recommendation"
                        />
                    )}
                </div>
            </div>
            <p className="text-xs text-secondary mt-1 mb-3">Stay ahead of new and resurfacing issues.</p>
            <div className="flex flex-col gap-0">
                {alerts.map((alert) => {
                    const info = ALERT_RECOMMENDATION_INFO[alert.key]
                    if (!info) {
                        return null
                    }
                    return (
                        <div
                            key={alert.key}
                            className={`flex items-center gap-3 py-2 border-b last:border-b-0 ${alert.enabled ? 'opacity-60' : ''}`}
                        >
                            <div
                                className={`w-1.5 h-1.5 rounded-full shrink-0 ${alert.enabled ? 'bg-success' : 'bg-muted'}`}
                            />
                            <div className="flex-1">
                                <span className="text-sm font-medium">{info.name}</span>
                                <p className="text-xs text-muted m-0">{info.reason}</p>
                            </div>
                            {!alert.enabled && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => {
                                        posthog.capture('error_tracking_alert_creation_started', {
                                            source: 'recommendation_modal',
                                            trigger_key: alert.key,
                                        })
                                        setOpenTriggerKey(alert.key)
                                    }}
                                >
                                    Create alert
                                </LemonButton>
                            )}
                        </div>
                    )
                })}
            </div>
            {openTriggerKey && (
                <AlertsRecommendationWizardModal
                    triggerKey={openTriggerKey}
                    onClose={() => {
                        setOpenTriggerKey(null)
                        refreshRecommendation(recommendation.id)
                    }}
                />
            )}
        </div>
    )
}

function AlertsRecommendationWizardModal({
    triggerKey,
    onClose,
}: {
    triggerKey: HogFunctionSubTemplateIdType
    onClose: () => void
}): JSX.Element {
    const wizardProps: AlertWizardLogicProps = {
        logicKey: `error-tracking-recommendation-${triggerKey}`,
        subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
        triggers: ERROR_TRACKING_TRIGGERS,
        destinations: ERROR_TRACKING_DESTINATIONS,
        disableUrlSync: true,
        presetTriggerKey: triggerKey,
        onAlertCreated: onClose,
    }

    return (
        <LemonModal isOpen onClose={onClose} width={560} simple>
            <BindLogic logic={alertWizardLogic} props={wizardProps}>
                <AlertsRecommendationWizardContent onClose={onClose} />
            </BindLogic>
        </LemonModal>
    )
}

function AlertsRecommendationWizardContent({ onClose }: { onClose: () => void }): JSX.Element {
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    return (
        <div className="p-4">
            <AlertWizard
                hideTriggerStep
                hideCloseButton
                onCancel={() => {
                    setAlertCreationView(AlertCreationView.None)
                    resetWizard()
                    onClose()
                }}
                onSwitchToTraditional={() => {
                    posthog.capture('error_tracking_alert_creation_switched_to_traditional', {
                        source: 'recommendation_modal',
                    })
                    resetWizard()
                    onClose()
                    router.actions.push(urls.errorTrackingConfiguration())
                }}
            />
        </div>
    )
}
