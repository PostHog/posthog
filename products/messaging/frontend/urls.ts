export const urls = {
    messagingBroadcasts: (): string => '/messaging/broadcasts',
    messagingBroadcast: (id?: string): string => `/messaging/broadcasts/${id}`,
    messagingBroadcastNew: (): string => '/messaging/broadcasts/new',
    messagingProviders: (): string => '/messaging/providers',
    messagingProvider: (id?: string): string => `/messaging/providers/${id}`,
    messagingProviderNew: (template?: string): string => '/messaging/providers/new' + (template ? `/${template}` : ''),
}
