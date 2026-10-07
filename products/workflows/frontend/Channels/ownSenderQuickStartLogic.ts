import { MakeLogicType, connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'

import { FirstRunSender, firstRunSenderLogic } from '../firstRun/firstRunSenderLogic'

export interface ownSenderQuickStartLogicValues {
    firstRunSender: FirstRunSender | null
    ownDomainTaskDone: boolean
}

export interface ownSenderQuickStartLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        ownDomainTaskDone: (firstRunSender: FirstRunSender | null) => boolean
    }
}

export type ownSenderQuickStartLogicType = MakeLogicType<
    ownSenderQuickStartLogicValues,
    Record<string, never>,
    Record<string, any>,
    ownSenderQuickStartLogicMeta
>

export const ownSenderQuickStartLogic = kea<ownSenderQuickStartLogicType>([
    path(['products', 'workflows', 'frontend', 'Channels', 'ownSenderQuickStartLogic']),
    connect({ values: [firstRunSenderLogic, ['firstRunSender']] }),
    selectors({
        ownDomainTaskDone: [
            (s) => [s.firstRunSender],
            (firstRunSender: FirstRunSender | null): boolean => !!firstRunSender,
        ],
    }),
    subscriptions({
        ownDomainTaskDone: (done: boolean) => {
            if (done) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.SendFromOwnEmailDomain)
            }
        },
    }),
])
