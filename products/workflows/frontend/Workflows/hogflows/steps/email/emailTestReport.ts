import posthog from 'posthog-js'

import type { HogFlow } from '../../types'
import type { HogflowTestResult } from '../types'
import { isEmailStep } from './emailStepVariants'
import { sandboxTestOutcome } from './sandboxTestResult'

type EmailSenderKind = 'sandbox' | 'own_domain'

export function reportEmailTest(workflow: HogFlow, actionId: string | null, result: HogflowTestResult): void {
    const action = workflow.actions?.find((candidate) => candidate.id === actionId)
    if (!isEmailStep(action) || result.mocked) {
        return
    }
    const onSandbox = action.type === 'email_sandbox'
    const sandboxOutcome = onSandbox ? sandboxTestOutcome(result) : null
    if (sandboxOutcome) {
        // pinned: analytics event name and properties, renaming breaks dashboards
        posthog.capture('workflows sandbox test sent', {
            status: sandboxOutcome.status,
            reason: sandboxOutcome.reason ?? null,
        })
    }
    const accepted = onSandbox
        ? sandboxOutcome?.status === 'accepted'
        : result.status === 'success' && result.emailSendResult?.status === 'accepted'
    if (accepted) {
        const senderKind: EmailSenderKind = onSandbox ? 'sandbox' : 'own_domain'
        // pinned: analytics event name and properties, renaming breaks dashboards
        posthog.capture('workflows test email sent', { step_type: action.type, sender_kind: senderKind })
    }
}
