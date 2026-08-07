export const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio', 'firebase', 'apns'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]
