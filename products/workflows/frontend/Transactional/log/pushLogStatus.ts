import type { LemonTagType } from '@posthog/lemon-ui'

import type { PushSendStatusEnumApi } from 'products/messaging/frontend/generated/api.schemas'

export const PUSH_STATUS_LABEL: Record<PushSendStatusEnumApi, string> = {
    sending: 'Sending',
    sent: 'Sent',
    not_sent: 'Not sent',
    failed: 'Failed',
}

export const PUSH_STATUS_TAG: Record<PushSendStatusEnumApi, LemonTagType> = {
    sending: 'default',
    sent: 'success',
    not_sent: 'warning',
    failed: 'danger',
}

export const PUSH_STATUS_DESCRIPTION: Record<PushSendStatusEnumApi, string> = {
    sending: 'Still going out.',
    sent: "Apple or Google accepted the push for at least one of the person's devices.",
    not_sent: "None of the person's devices got the push, for example because none is registered or its token expired.",
    failed: 'The send stopped with an error.',
}
