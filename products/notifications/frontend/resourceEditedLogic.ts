import { actions, kea, path } from 'kea'

import { ResourceEditedEvent } from '~/types'

import type { resourceEditedLogicType } from './resourceEditedLogicType'

/** Discriminator on `notification_type` for transient "edited elsewhere" events on the SSE stream. */
export const RESOURCE_EDITED_EVENT_TYPE = 'resource_edited'

/**
 * A tiny event bus that decouples the notifications SSE consumer from editors that care about
 * "this resource was edited elsewhere" events. The SSE consumer (sidePanelNotificationsLogic)
 * forwards matching events here; interested editors (e.g. workflowLogic) connect to the
 * `resourceEdited` action and decide what to do — silently refresh or warn before clobbering.
 *
 * Kept deliberately logic-free so neither side has to depend on the other's internals.
 */
export const resourceEditedLogic = kea<resourceEditedLogicType>([
    path(['products', 'notifications', 'frontend', 'resourceEditedLogic']),
    actions({
        resourceEdited: (event: ResourceEditedEvent) => ({ event }),
    }),
])
