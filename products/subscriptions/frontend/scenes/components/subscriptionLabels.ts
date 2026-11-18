import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'
import { SubscriptionTargetEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

export const TARGET_TYPE_LABEL: Record<SubscriptionApi['target_type'], string> = {
    [SubscriptionTargetEnumApi.Email]: 'Email',
    [SubscriptionTargetEnumApi.Slack]: 'Slack',
    [SubscriptionTargetEnumApi.Teams]: 'Microsoft Teams',
}
