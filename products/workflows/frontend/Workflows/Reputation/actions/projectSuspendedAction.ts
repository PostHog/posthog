import { defineReputationAction } from './defineReputationAction'
import { contactSupport } from './reputationActionCtas'

/** PostHog suspended all email for the project. Only support can lift it. */
export const projectSuspendedAction = defineReputationAction<true>({
    kind: 'project-suspended',
    detect: (context) => (context.suspended ? [true] : []),
    content: () => ({
        key: 'project-suspended',
        severity: 'high',
        slot: 'sendingStopped',
        blocksSending: true,
        title: 'PostHog suspended email sending for this project',
        description:
            'No workflow email goes out until the suspension ends. Fix the other items here, then contact support to lift it.',
    }),
    cta: () =>
        contactSupport(
            'Email sending is suspended for this project. Please review it and lift the suspension. What I changed: '
        ),
})
