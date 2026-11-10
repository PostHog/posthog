import { IconWarning } from '@posthog/icons'

import {
    ERROR_TRACKING_ISSUE_CREATED_EVENT,
    isErrorTrackingIssueCreatedTriggerConfig,
} from './errorTrackingIssueTrigger'
import { StepTriggerConfigurationErrorTrackingIssue } from './StepTriggerConfigurationErrorTrackingIssue'
import { registerTriggerType } from './triggerTypeRegistry'

registerTriggerType({
    value: 'error-tracking-issue-created',
    label: 'Issue created',
    icon: <IconWarning />,
    description: 'Trigger when Error tracking creates a new issue',
    group: 'Error tracking',
    matchConfig: isErrorTrackingIssueCreatedTriggerConfig,
    buildConfig: () => ({
        type: 'internal-event',
        filters: {
            source: 'internal-events',
            events: [{ id: ERROR_TRACKING_ISSUE_CREATED_EVENT, type: 'events', name: 'Issue created' }],
            properties: [],
        },
    }),
    ConfigComponent: StepTriggerConfigurationErrorTrackingIssue,
})
