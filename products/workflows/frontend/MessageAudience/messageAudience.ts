import posthog from 'posthog-js'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import {
    AccessControlLevel,
    AccessControlResourceType,
    AnyPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

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
    /** The record the email is about, as "<kind>:<id>". A broadcast skips the people already emailed about it. */
    sourceRecord?: string
    /** What the record is called, for naming the cohort of people already emailed about it. */
    sourceRecordName?: string
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
            sourceRecord: audience.sourceRecord,
            email: audience.broadcastEmail,
        })
    }
    return urlForNewWorkflowWithTrigger(
        audience.workflowTrigger ?? { type: 'batch', filters: { properties: audience.properties } },
        audience.source,
        audience.workflowEmail
    )
}

export function captureMessageAudienceClicked(source: string, destination: MessageAudienceDestination): void {
    // pinned: analytics event name
    posthog.capture('message audience clicked', { source, destination })
}

/** Why this person can't start a broadcast or workflow, if they can't: both need editor access to workflows. */
export function messageAudienceAccessDisabledReason(): string | null {
    return getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor)
}
