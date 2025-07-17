import { kea, key, path, props, selectors } from 'kea'
import { IntegrationType } from '~/types'

import type { messageChannelLogicType } from './messageChannelLogicType'

export interface MessageChannelLogicProps {
    integration?: IntegrationType
}

export const messageChannelLogic = kea<messageChannelLogicType>([
    path(['products', 'messaging', 'frontend', 'messageChannelLogic']),
    props({} as MessageChannelLogicProps),
    key(({ integration }) => `${integration?.kind}-${integration?.id}`),
    selectors(() => ({
        displayName: [
            () => [(_, props) => props],
            ({ integration }): string => {
                switch (integration?.kind) {
                    case 'email':
                        return integration.config.domain
                    case 'twilio':
                        return integration.config.phone_number
                    default:
                        return integration.display_name
                }
            },
        ],
        isVerificationRequired: [
            () => [(_, props) => props],
            ({ integration }): boolean => {
                return ['email', 'twilio'].includes(integration?.kind)
            },
        ],
        isVerified: [
            () => [(_, props) => props],
            ({ integration }): boolean => {
                switch (integration?.kind) {
                    case 'email':
                        return integration.config.mailjet_verified === true
                    default:
                        return true
                }
            },
        ],
    })),
])
