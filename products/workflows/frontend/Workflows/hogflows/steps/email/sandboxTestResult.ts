import posthog from 'posthog-js'

import { LemonBannerProps } from 'lib/lemon-ui/LemonBanner'

import type { HogFlow } from '../../types'
import type { HogflowTestResult } from '../types'

export type SandboxTestStatus = 'accepted' | 'skipped' | 'failed' | 'pending'

export interface SandboxTestOutcome {
    status: SandboxTestStatus
    reason?: string
    mocked?: boolean
}

const STATUSES: readonly string[] = ['accepted', 'skipped', 'failed', 'pending']

const REASONS: Record<string, string> = {
    not_member: 'The sandbox sender only delivers to verified members of your organization.',
    ambiguous_member: 'More than one member uses this address, so the sandbox sender skipped it.',
    organization_blocked: 'Sandbox email is turned off for your organization.',
    team_not_found: "This project couldn't be found.",
    authorization_unavailable: "Couldn't check the recipient.",
    pause_state_unavailable: "Couldn't check whether the sandbox sender is available.",
    tenant_paused: 'Sandbox email is paused for this project.',
    sending_suspended: 'Email sending is suspended for this project. Contact support to get sending re-enabled.',
    sending_paused: 'Email sending is paused for this workflow. Resume sending, then send the test again.',
    suspension_state_unavailable: "Couldn't check whether this project can send email.",
    daily_cap_reached: "This project reached today's sandbox email limit.",
    cap_storage_unavailable: "Couldn't check today's sandbox email limit.",
    suppressed: 'This address bounced or marked an earlier email as spam.',
    opted_out: 'The recipient opted out of this message category.',
    frequency_capped: 'The recipient already received the most emails allowed for now.',
    invalid_recipient: "The recipient address isn't a valid email address.",
    sandbox_not_provisioned: "The sandbox sender isn't set up for this project yet.",
    sending_disabled: 'Sandbox email sending is turned off.',
    render_failed: "The email couldn't be rendered. Check the subject and content for template errors.",
    retries_exhausted: 'Sending kept failing, so it stopped retrying.',
    ses_throttled: 'The email service is busy.',
    ses_transient: 'The email service had a temporary problem.',
    ses_rejected: 'The email service rejected this email.',
    sandbox_worker_unavailable: "The sandbox sender couldn't be reached.",
    sandbox_worker_unreachable: "The sandbox sender couldn't be reached.",
    send_rate_limited: 'Too many emails are being sent right now. Send the test again in a moment.',
    unsupported_action_id: "The sandbox sender can't send from this step. Delete the step and add it again.",
}

export function sandboxTestOutcome(result: HogflowTestResult | null): SandboxTestOutcome | null {
    const execResult = result?.execResult as Record<string, unknown> | null | undefined
    if (!execResult || typeof execResult.status !== 'string' || !STATUSES.includes(execResult.status)) {
        return null
    }
    return {
        status: execResult.status as SandboxTestStatus,
        ...(typeof execResult.reason === 'string' ? { reason: execResult.reason } : {}),
        ...(result?.mocked ? { mocked: true } : {}),
    }
}

export function reportSandboxTest(workflow: HogFlow, actionId: string | null, result: HogflowTestResult): void {
    const action = workflow.actions?.find((candidate) => candidate.id === actionId)
    const outcome = action?.type === 'email_sandbox' && !result.mocked ? sandboxTestOutcome(result) : null
    if (outcome) {
        // pinned: analytics event name and properties, renaming breaks dashboards
        posthog.capture('workflows sandbox test sent', { status: outcome.status, reason: outcome.reason ?? null })
    }
}

export function sandboxTestBanner({ status, reason, mocked }: SandboxTestOutcome): LemonBannerProps {
    const explanation = reason ? (REASONS[reason] ?? `Reason: ${reason}.`) : null
    const sentence = (...parts: (string | null)[]): string => parts.filter(Boolean).join(' ')
    switch (status) {
        case 'accepted':
            return mocked
                ? {
                      type: 'success',
                      children:
                          'Test passed without sending. Turn on real HTTP requests to send from the sandbox sender.',
                  }
                : { type: 'success', children: 'Sent from the sandbox sender.' }
        case 'pending':
            return { type: 'warning', children: sentence('Not sent yet.', explanation, 'Try again in a few minutes.') }
        case 'skipped':
            return { type: 'warning', children: sentence('Not sent.', explanation) }
        case 'failed':
            return { type: 'error', children: sentence("Couldn't send.", explanation ?? 'Try again later.') }
    }
}
