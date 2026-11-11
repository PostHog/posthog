import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { HogFlow } from './hogflows/types'

/** A broadcast isn't in the workflows list, so going back from its editor returns to the broadcast. */
export function workflowBackTo(workflow: HogFlow | null | undefined, id: string | undefined): Breadcrumb | undefined {
    return workflow?.origin_product === 'broadcasts' && id && id !== 'new'
        ? { key: 'broadcast', name: workflow.name || 'the broadcast', path: urls.broadcast(id) }
        : undefined
}
