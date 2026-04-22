import { IntegrationType } from '~/types'

import { APNSSetupModal } from './APNSSetup/APNSSetupModal'
import { EmailSetupModal } from './EmailSetup/EmailSetupModal'
import { FCMSetupModal } from './FCMSetup/FCMSetupModal'
import { ChannelType } from './MessageChannels'
import { SlackSetupModal } from './SlackSetup/SlackSetupModal'
import { TwilioSetupModal } from './TwilioSetup/TwilioSetupModal'

interface ChannelSetupModalProps {
    isOpen: boolean
    channelType: ChannelType | null
    integration: IntegrationType | undefined
    onComplete: () => void
    onClose: () => void
}

export function ChannelSetupModal({
    isOpen,
    channelType,
    integration,
    onComplete,
    onClose,
}: ChannelSetupModalProps): JSX.Element | null {
    if (!isOpen || !channelType) {
        return null
    }

    const modalProps = {
        integration,
        onComplete,
        onClose,
    }

    switch (channelType) {
        case 'email':
            return <EmailSetupModal {...modalProps} />
        case 'slack':
            return <SlackSetupModal {...modalProps} />
        case 'twilio':
            return <TwilioSetupModal {...modalProps} />
        case 'firebase':
            return <FCMSetupModal {...modalProps} />
        case 'apns':
            return <APNSSetupModal {...modalProps} />

        default:
            return null
    }
}
