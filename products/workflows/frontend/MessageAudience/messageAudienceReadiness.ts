import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { IntegrationType } from '~/types'

import type { CohortApi } from 'products/cohorts/frontend/generated/api.schemas'

import {
    EMAIL_SENDING_SUSPENDED_MESSAGE,
    NO_EMAIL_SENDER_MESSAGE,
    UNVERIFIED_SENDER_MESSAGE,
    broadcastLimitMessage,
} from '../Channels/emailSendingMessages'

export interface MessageAudienceSize {
    /** How many emails a broadcast to this audience would send, counting people without an address. Launch checks this against the limit. */
    reach: number
    withEmail: number
    limit: number
}

export interface MessageAudienceCohort {
    name: string
    isStatic: boolean
    /** Matching people for the first time, or a static list still importing. Its members aren't final yet. */
    pending: boolean
    failed: boolean
}

export type MessageAudienceCountState = 'loading' | 'pending' | 'failed' | 'ready'

export interface MessageAudienceReadiness {
    countState: MessageAudienceCountState
    /** People with an email address, once the count is final. */
    count: number | null
    disabledReason: string | null
    /** Problems the person should know about before they write the email. None of them stop them from starting. */
    warnings: string[]
}

export function toMessageAudienceCohort(cohort: CohortApi): MessageAudienceCohort {
    const isCalculating = !!cohort.is_calculating
    return {
        name: cohort.name || 'This cohort',
        isStatic: !!cohort.is_static,
        // A dynamic cohort keeps its members while it recalculates, so only its first calculation leaves it empty.
        pending: isCalculating && (!!cohort.is_static || !cohort.last_calculation),
        failed: !isCalculating && (cohort.errors_calculating ?? 0) > 0,
    }
}

export function emailSenderWarning(integrations: IntegrationType[] | null): string | null {
    if (!integrations) {
        return null
    }
    const senders = integrations.filter((integration) => integration.kind === 'email')
    if (senders.length === 0) {
        return NO_EMAIL_SENDER_MESSAGE
    }
    if (!senders.some((integration) => integration.config?.verified === true)) {
        return UNVERIFIED_SENDER_MESSAGE
    }
    return null
}

export function emailSuspensionWarning(suspended: boolean): string | null {
    return suspended ? EMAIL_SENDING_SUSPENDED_MESSAGE : null
}

export function overLimitWarning(size: MessageAudienceSize | null): string | null {
    if (!size || size.reach <= size.limit) {
        return null
    }
    return `${broadcastLimitMessage(size.limit)} This audience has ${humanFriendlyNumber(size.reach)} people. Narrow it before sending.`
}

export function messageAudienceReadiness({
    size,
    sizeLoading,
    sizeFailed,
    cohorts,
    integrations,
    emailSendingSuspended,
}: {
    size: MessageAudienceSize | null
    sizeLoading: boolean
    sizeFailed: boolean
    cohorts: MessageAudienceCohort[]
    integrations: IntegrationType[] | null
    emailSendingSuspended: boolean
}): MessageAudienceReadiness {
    const warnings: string[] = []
    const suspension = emailSuspensionWarning(emailSendingSuspended)
    const sender = emailSenderWarning(integrations)
    for (const warning of [suspension, sender]) {
        if (warning) {
            warnings.push(warning)
        }
    }
    for (const cohort of cohorts) {
        if (cohort.pending) {
            warnings.push(
                `"${cohort.name}" is still calculating who's in it. You can write the email now and send it once it finishes.`
            )
        } else if (cohort.failed) {
            warnings.push(`"${cohort.name}" couldn't calculate who's in it. Open the cohort to see why.`)
        }
    }

    if (cohorts.some((cohort) => cohort.pending)) {
        return { countState: 'pending', count: null, disabledReason: null, warnings }
    }
    if (!size) {
        return {
            countState: sizeLoading || !sizeFailed ? 'loading' : 'failed',
            count: null,
            disabledReason: null,
            warnings,
        }
    }
    const limitWarning = overLimitWarning(size)
    if (limitWarning) {
        warnings.push(limitWarning)
    }
    const disabledReason =
        size.withEmail > 0
            ? null
            : size.reach === 0
              ? 'No one is in this audience yet'
              : 'No one in this audience has an email address'
    return { countState: 'ready', count: size.withEmail, disabledReason, warnings }
}

export function messageAudienceButtonLabel(readiness: MessageAudienceReadiness, fallback: string): string {
    if (readiness.countState !== 'ready' || !readiness.count) {
        return fallback
    }
    return `Email ${pluralize(readiness.count, 'person', 'people')}`
}

export function messageAudienceTooltip(readiness: MessageAudienceReadiness): string | undefined {
    if (readiness.warnings.length > 0) {
        return readiness.warnings.join(' ')
    }
    if (readiness.countState === 'failed') {
        return "Couldn't count the people in this audience. You'll see the count before you send."
    }
    return undefined
}
