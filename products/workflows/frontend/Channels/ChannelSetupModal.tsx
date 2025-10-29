import { IntegrationType } from '~/types'

import { EmailSetupModal } from './EmailSetup/EmailSetupModal'
import { ChannelType } from './MessageChannels'
import { SlackSetupModal } from './SlackSetup/SlackSetupModal'
import { TwilioSetupModal } from './TwilioSetup/TwilioSetupModal'

interface ChannelSetupModalProps {
    isOpen: boolean
    channelType: ChannelType | null
    integration: IntegrationType | undefined
    onComplete: () => void
}

export function ChannelSetupModal({
    isOpen,
    channelType,
    integration,
    onComplete,
}: ChannelSetupModalProps): JSX.Element | null {
    if (!isOpen || !channelType) {
        return null
    }

    const modalProps = {
        integration,
        onComplete,
    }

    switch (channelType) {
        case 'email':
            return <EmailSetupModal {...modalProps} />
        case 'slack':
            return <SlackSetupModal {...modalProps} />
        case 'twilio':
            return <TwilioSetupModal {...modalProps} />

        default:
            return null
    }
}
