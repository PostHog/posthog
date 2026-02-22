import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AlertWizard } from 'scenes/hog-functions/AlertWizard/AlertWizard'
import {
    AlertWizardLogicProps,
    WizardDestination,
    WizardTrigger,
    alertWizardLogic,
} from 'scenes/hog-functions/AlertWizard/alertWizardLogic'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType } from '~/types'

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

const ERROR_TRACKING_DESTINATIONS: WizardDestination[] = [
    {
        key: 'slack',
        name: 'Slack',
        description: 'Send a message to a channel',
        icon: '/static/services/slack.png',
        templateId: 'template-slack',
    },
    {
        key: 'discord',
        name: 'Discord',
        description: 'Post a notification via webhook',
        icon: '/static/services/discord.png',
        templateId: 'template-discord',
    },
    {
        key: 'github',
        name: 'GitHub',
        description: 'Create an issue in a repository',
        icon: '/static/services/github.png',
        templateId: 'template-github',
    },
    {
        key: 'microsoft-teams',
        name: 'Microsoft Teams',
        description: 'Send a message to a channel',
        icon: '/static/services/microsoft-teams.png',
        templateId: 'template-microsoft-teams',
    },
    {
        key: 'linear',
        name: 'Linear',
        description: 'Create an issue in a project',
        icon: '/static/services/linear.png',
        templateId: 'template-linear',
    },
]

const ERROR_TRACKING_DESTINATION_PRIORITY = ERROR_TRACKING_DESTINATIONS.map((d) => d.key)

const HOG_FUNCTION_FILTER_LIST = ERROR_TRACKING_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

const ALERT_WIZARD_PROPS: AlertWizardLogicProps = {
    logicKey: 'error-tracking',
    subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
    triggers: ERROR_TRACKING_TRIGGERS,
    destinations: ERROR_TRACKING_DESTINATIONS,
    destinationPriority: ERROR_TRACKING_DESTINATION_PRIORITY,
    urlPattern: '**/error_tracking/configuration',
    sourceName: 'Error tracking alert wizard',
}

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <BindLogic logic={alertWizardLogic} props={ALERT_WIZARD_PROPS}>
            <ErrorTrackingAlertingInner />
        </BindLogic>
    )
}

function ErrorTrackingAlertingInner(): JSX.Element {
    const { alertCreationView, subTemplateIds } = useValues(alertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    if (alertCreationView === 'wizard') {
        return (
            <AlertWizard
                onCancel={() => {
                    setAlertCreationView('none')
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    setAlertCreationView('traditional')
                    resetWizard()
                }}
            />
        )
    }

    if (alertCreationView === 'traditional') {
        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={subTemplateIds}
                getConfigurationOverrides={(id) => (id ? getFiltersFromSubTemplateId(id) : undefined)}
                extraControls={
                    <LemonButton type="secondary" size="small" onClick={() => setAlertCreationView('none')}>
                        Cancel
                    </LemonButton>
                }
            />
        )
    }

    return (
        <HogFunctionList
            forceFilterGroups={HOG_FUNCTION_FILTER_LIST}
            type="internal_destination"
            extraControls={
                <LemonButton type="primary" size="small" onClick={() => setAlertCreationView('wizard')}>
                    New notification
                </LemonButton>
            }
        />
    )
}
