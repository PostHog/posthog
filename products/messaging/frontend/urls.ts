export const messagingBroadcasts = (): string => '/messaging/broadcasts'
export const messagingBroadcast = (id?: string): string => `/messaging/broadcasts/${id}`
export const messagingBroadcastNew = (): string => '/messaging/broadcasts/new'
export const messagingProviders = (): string => '/messaging/providers'
export const messagingProvider = (id?: string): string => `/messaging/providers/${id}`
export const messagingProviderNew = (template?: string): string => '/messaging/providers/new' + (template ? `/${template}` : '')
