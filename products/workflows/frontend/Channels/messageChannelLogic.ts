import { kea, key, path, props, selectors } from 'kea'

import { IntegrationType } from '~/types'

import type { messageChannelLogicType } from './messageChannelLogicType'

export interface MessageChannelLogicProps {
    integration?: IntegrationType
}

export const messageChannelLogic = kea<messageChannelLogicType>([
    path(['products', 'workflows', 'frontend', 'messageChannelLogic']),
    props({} as MessageChannelLogicProps),
    key(({ integration }) => `${integration?.kind}-${integration?.id}`),
    selectors(() => ({
        displayName: [
            () => [(_, props) => props],
            ({ integration }): string => {
                switch (integration?.kind) {
                    case 'email':
                        return integration.config.domain
                    default:
                        return integration.display_name
                }
            },
        ],
        isVerificationRequired: [
            () => [(_, props) => props],
            ({ integration }): boolean => {
                return ['email'].includes(integration?.kind)
            },
        ],
        isVerified: [
            () => [(_, props) => props],
            ({ integration }): boolean => {
                switch (integration?.kind) {
                    case 'email':
                        return integration.config.verified === true
                    default:
                        return true
                }
            },
        ],
    })),
])
