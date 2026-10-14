import posthog from 'posthog-js'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { urlForNewBroadcastWithAudience } from '../Broadcasts/broadcastAudiencePrefill'
import { type WorkflowTriggerConfig, urlForNewWorkflowWithTrigger } from '../Workflows/workflowTriggerPrefill'
import { MessageDraft } from './messageDrafts'

export type MessageAudienceDestination = 'broadcast' | 'workflow'

export interface MessageAudience {
    properties: AnyPropertyFilter[]
    source: string
    broadcastName?: string
    /** The workflow to start. Without one, the workflow sends to the same people with a batch trigger. */
    workflowTrigger?: WorkflowTriggerConfig
    broadcastEmail?: MessageDraft
    workflowEmail?: MessageDraft
}

export function cohortAudienceProperties(cohort: { id: number; name?: string | null }): AnyPropertyFilter[] {
    return [
        {
            key: 'id',
            type: PropertyFilterType.Cohort,
            value: cohort.id,
            operator: PropertyOperator.In,
            cohort_name: cohort.name ?? undefined,
        },
    ]
}

export function messageAudienceUrl(audience: MessageAudience, destination: MessageAudienceDestination): string {
    if (destination === 'broadcast') {
        return urlForNewBroadcastWithAudience({
            properties: audience.properties,
            name: audience.broadcastName,
            source: audience.source,
            email: audience.broadcastEmail,
        })
    }
    return urlForNewWorkflowWithTrigger(
        audience.workflowTrigger ?? { type: 'batch', filters: { properties: audience.properties } },
        audience.source,
        audience.workflowEmail
    )
}

export function captureMessageAudienceClicked(
    source: string,
    destination: MessageAudienceDestination,
    extra: { succeeded?: boolean } = {}
): void {
    // pinned: analytics event name
    posthog.capture('message audience clicked', { source, destination, ...extra })
}
