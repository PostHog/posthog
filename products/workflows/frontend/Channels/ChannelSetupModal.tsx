import { IntegrationType } from '~/types'

import { APNSSetupModal } from './APNSSetup/APNSSetupModal'
import { EmailSetupModal } from './EmailSetup/EmailSetupModal'
import { EmailSetupSurface } from './EmailSetup/emailSetupModalLogic'
import { FCMSetupModal } from './FCMSetup/FCMSetupModal'
import { ChannelType } from './MessageChannels'
import { SlackSetupModal } from './SlackSetup/SlackSetupModal'
import { TwilioSetupModal } from './TwilioSetup/TwilioSetupModal'

interface ChannelSetupModalProps {
    isOpen: boolean
    channelType: ChannelType | null
    integration: IntegrationType | undefined
    surface: EmailSetupSurface
    onComplete: () => void
    onClose: () => void
    onEmailSenderCreated?: () => void
}

export function ChannelSetupModal({
    isOpen,
    channelType,
    integration,
    surface,
    onComplete,
    onClose,
    onEmailSenderCreated,
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
            return <EmailSetupModal {...modalProps} surface={surface} onSenderCreated={onEmailSenderCreated} />
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
