import { LemonDialog } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { hogFlowsResumeEmailSending } from '../generated/api'
import type { HogFlowEmailSendingRateLimitApi } from '../generated/api.schemas'

export interface EmailSendingPause {
    paused: boolean
    reason: string
    /** Only PostHog staff can lift the pause. */
    pausedByStaff: boolean
    /** Staff pauses and repeat pauses (tripped again soon after a resume) have no resume button. */
    requiresSupport: boolean
}

interface PausableFlow {
    email_sending_paused_at?: string | null
    email_sending_paused_reason?: string | null
    email_sending_paused_by?: string | null
    email_sending_pause_requires_support?: boolean | null
}

/** Read off the saved row, never an editor form: a pause is server state. */
export function emailSendingPause(flow: PausableFlow | null | undefined): EmailSendingPause {
    return {
        paused: !!flow?.email_sending_paused_at,
        reason: flow?.email_sending_paused_reason ?? '',
        pausedByStaff: flow?.email_sending_paused_by === 'staff',
        requiresSupport: flow?.email_sending_pause_requires_support === true,
    }
}

export function openResumeEmailSendingDialog(subject: 'workflow' | 'broadcast', onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Resume email sending?',
        description: `Send again from this ${subject}. If it keeps drawing spam complaints or hitting addresses that do not exist, sending pauses again on its own within a couple of hours.`,
        primaryButton: {
            children: 'Resume sending',
            onClick: onConfirm,
            'data-attr': `${subject}-email-paused-resume-confirm`,
        },
        secondaryButton: { children: 'Cancel' },
    })
}

/** Resumes sending and toasts the outcome. Never throws, because the caller reloads the flow either way. */
export async function requestResumeEmailSending(projectId: string, id: string): Promise<void> {
    try {
        await hogFlowsResumeEmailSending(projectId, id)
        lemonToast.success('Email sending resumed')
    } catch {
        lemonToast.error('Could not resume email sending. Please try again.')
    }
}

export function sendingRateSummary(limit: HogFlowEmailSendingRateLimitApi): string {
    return `At most ${humanFriendlyNumber(limit.count)} emails per ${limit.period}`
}
