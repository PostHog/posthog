import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { WorkflowEmailSendingRatesApi } from 'products/workflows/frontend/generated/api.schemas'

import { TRIGGER_NODE_ID } from '../../workflowLogic'
import { CHANNEL_SETUP_DOCS_URL, LOWER_RATES_DOCS_URL } from '../reputationUtils'
import type { ReputationActionContext } from './reputationActionContext'
import type { ReputationActionCta, ReputationDocsLink } from './reputationActionTypes'

export const LOWER_RATES_DOCS: ReputationDocsLink = { label: 'How to lower your rates', to: LOWER_RATES_DOCS_URL }

export const CHANNEL_SETUP_DOCS: ReputationDocsLink = { label: 'Channel setup guide', to: CHANNEL_SETUP_DOCS_URL }

export function contactSupport(message: string): ReputationActionCta {
    return { label: 'Contact support', onClick: (page) => page.openSupportForm(message) }
}

// Items that name no workflow still ask the user to find the ones with high rates, and the
// workflow table below the list shows every workflow's rates.
export const VIEW_WORKFLOWS: ReputationActionCta = {
    label: 'View workflows',
    onClick: (page) => page.showBreakdown('workflows'),
}

export const VIEW_PROVIDERS: ReputationActionCta = {
    label: 'View providers',
    onClick: (page) => page.showBreakdown('providers'),
}

// Every item that names a workflow asks the user to check its audience, and the trigger step
// holds the audience. The workflow editor reads `node` from the URL and selects that step. The
// reputation rows carry no origin, so a broadcast opens in the workflow editor too.
export function openWorkflow(workflow: WorkflowEmailSendingRatesApi): ReputationActionCta {
    return {
        label: 'Open workflow',
        to: combineUrl(urls.workflow(workflow.hog_flow_id, 'workflow'), { node: TRIGGER_NODE_ID }).url,
    }
}

export function manageOptOuts(context: ReputationActionContext): ReputationActionCta {
    return { label: 'Manage opt-outs', to: context.tabUrl('opt-outs') }
}

export function openChannels(context: ReputationActionContext): ReputationActionCta {
    return { label: 'Open channels', to: context.tabUrl('channels') }
}
