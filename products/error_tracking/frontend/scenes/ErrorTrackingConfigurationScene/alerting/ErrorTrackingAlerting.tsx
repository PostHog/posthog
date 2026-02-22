import { BindLogic } from 'kea'

import { AlertWizardAlerting } from 'scenes/hog-functions/AlertWizard/AlertWizardAlerting'
import {
    AlertWizardLogicProps,
    WizardTrigger,
    alertWizardLogic,
} from 'scenes/hog-functions/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

const ERROR_TRACKING_SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = [
    'error-tracking-issue-created',
    'error-tracking-issue-reopened',
    'error-tracking-issue-spiking',
]

const ERROR_TRACKING_TRIGGERS: WizardTrigger[] = [
    {
        key: 'error-tracking-issue-created',
        name: 'Issue created',
        description: 'Get notified when a new error issue is detected',
    },
    {
        key: 'error-tracking-issue-reopened',
        name: 'Issue reopened',
        description: 'Get notified when a previously resolved issue comes back',
    },
]

const ALERT_WIZARD_PROPS: AlertWizardLogicProps = {
    logicKey: 'error-tracking',
    subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
    triggers: ERROR_TRACKING_TRIGGERS,
    urlPattern: '**/error_tracking/configuration',
    sourceName: 'Error tracking alert wizard',
}

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <BindLogic logic={alertWizardLogic} props={ALERT_WIZARD_PROPS}>
            <AlertWizardAlerting />
        </BindLogic>
    )
}
