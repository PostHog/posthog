import { humanFriendlyNumber } from 'lib/utils/numbers'

export const EMAIL_SENDING_SUSPENDED_MESSAGE =
    'Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.'

export const UNVERIFIED_SENDER_MESSAGE = "Verify the sender's domain before sending"

export const NO_EMAIL_SENDER_MESSAGE = 'Set up an email sender before sending'

export function broadcastLimitMessage(limit: number): string {
    return `This project can send a broadcast to up to ${humanFriendlyNumber(limit)} people right now.`
}
