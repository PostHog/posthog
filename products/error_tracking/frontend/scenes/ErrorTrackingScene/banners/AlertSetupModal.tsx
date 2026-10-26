import { BindLogic, useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonModal } from '@posthog/lemon-ui'

import { AlertWizard } from 'lib/components/Alerting/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
} from 'lib/components/Alerting/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

import {
    ERROR_TRACKING_DESTINATIONS,
    ERROR_TRACKING_SUB_TEMPLATE_IDS,
    ERROR_TRACKING_TRIGGERS,
} from '../../ErrorTrackingConfigurationScene/alerting/alertWizardConfig'
import { errorTrackingConfigurationSettingUrl } from './configurationSettingUrl'

export function AlertSetupModal({
    triggerKey,
    onClose,
}: {
    /** `null` shows the trigger step so the user picks which alert to set up. */
    triggerKey: HogFunctionSubTemplateIdType | null
    onClose: () => void
}): JSX.Element {
    const wizardProps: AlertWizardLogicProps = {
        logicKey: `error-tracking-alerts-banner-${triggerKey ?? 'any'}`,
        subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
        triggers: ERROR_TRACKING_TRIGGERS,
        destinations: ERROR_TRACKING_DESTINATIONS,
        disableUrlSync: true,
        presetTriggerKey: triggerKey ?? undefined,
        contextId: 'error-tracking',
        onAlertCreated: onClose,
    }

    return (
        <LemonModal isOpen onClose={onClose} width={560} simple>
            <BindLogic logic={alertWizardLogic} props={wizardProps}>
                <AlertSetupWizard hideTriggerStep={triggerKey !== null} onClose={onClose} />
            </BindLogic>
        </LemonModal>
    )
}

function AlertSetupWizard({
    hideTriggerStep,
    onClose,
}: {
    hideTriggerStep: boolean
    onClose: () => void
}): JSX.Element {
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    return (
        <div className="p-4">
            <AlertWizard
                hideTriggerStep={hideTriggerStep}
                hideCloseButton
                onCancel={() => {
                    setAlertCreationView(AlertCreationView.None)
                    resetWizard()
                    onClose()
                }}
                onSwitchToTraditional={() => {
                    posthog.capture('error_tracking_alert_creation_switched_to_traditional', {
                        ui_source: 'alerts_banner',
                    })
                    resetWizard()
                    onClose()
                    router.actions.push(errorTrackingConfigurationSettingUrl('error-tracking-alerting'))
                }}
            />
        </div>
    )
}
