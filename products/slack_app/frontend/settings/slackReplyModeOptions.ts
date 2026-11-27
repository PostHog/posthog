import type {
    SlackChannelWelcomeModeEnumApi,
    SlackThreadJoinModeEnumApi,
    SlackUntaggedModeEnumApi,
} from '../generated/api.schemas'

export const UNTAGGED_MODE_OPTIONS: { value: SlackUntaggedModeEnumApi; label: string }[] = [
    { value: 'ask', label: 'Ask first' },
    { value: 'auto', label: 'Automatically' },
    { value: 'never', label: 'Never' },
]

export const THREAD_JOIN_OPTIONS: { value: SlackThreadJoinModeEnumApi; label: string }[] = [
    { value: 'allow', label: 'Let anyone join' },
    { value: 'ask_per_person', label: 'Ask me for each person' },
    { value: 'ask_per_thread', label: 'Ask me once for each thread' },
    { value: 'never', label: 'Ignore them' },
]

export const CHANNEL_WELCOME_OPTIONS: { value: SlackChannelWelcomeModeEnumApi; label: string }[] = [
    { value: 'channel', label: 'Post in the channel' },
    { value: 'inviter', label: 'Only the person who added the app' },
    { value: 'off', label: 'No greeting' },
]

// What a person who never picked gets when the workspace has no default either. Matches the backend resolvers.
export const POSTHOG_DEFAULT_UNTAGGED_MODE: SlackUntaggedModeEnumApi = 'ask'
export const POSTHOG_DEFAULT_THREAD_JOIN_MODE: SlackThreadJoinModeEnumApi = 'allow'

export function replyModeLabel<T extends string>(options: { value: T; label: string }[], value: T): string {
    return options.find((option) => option.value === value)?.label ?? value
}
