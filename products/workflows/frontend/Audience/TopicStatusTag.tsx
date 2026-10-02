import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import type { PreferenceStatusEnumApi } from 'products/messaging/frontend/generated/api.schemas'

const STATUS_LABELS: Record<PreferenceStatusEnumApi, string> = {
    OPTED_IN: 'Subscribed',
    OPTED_OUT: 'Unsubscribed',
    NO_PREFERENCE: 'No preference',
}

const STATUS_TAG_TYPES: Record<PreferenceStatusEnumApi, LemonTagType> = {
    OPTED_IN: 'success',
    OPTED_OUT: 'warning',
    NO_PREFERENCE: 'muted',
}

export interface TopicStatusTagProps {
    status: PreferenceStatusEnumApi
    topicName?: string
}

export function TopicStatusTag({ status, topicName }: TopicStatusTagProps): JSX.Element {
    const label = topicName ? `${topicName}: ${STATUS_LABELS[status]}` : STATUS_LABELS[status]
    return (
        <LemonTag type={STATUS_TAG_TYPES[status]} size="small" wrap>
            {label}
        </LemonTag>
    )
}
