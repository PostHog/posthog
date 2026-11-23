import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

export type SandboxSenderEnableSurface = 'editor' | 'list'

export function confirmEnableOnSandboxSender(
    workflowId: string,
    surface: SandboxSenderEnableSurface,
    onEnable: () => void
): void {
    // pinned: analytics event names and property values
    posthog.capture('workflows sandbox sender enable warning shown', { workflow_id: workflowId, surface })
    // The dialog stays clickable while it animates closed, and a second click would save twice.
    let confirmed = false
    LemonDialog.open({
        title: 'Enable on the PostHog test sender?',
        maxWidth: '36rem',
        description:
            'This workflow has email steps on the PostHog test sender. Those steps reach only verified members of your organization, and everyone else is skipped. To reach your users, set up your sending domain and switch those steps to it.',
        primaryButton: {
            children: 'Enable anyway',
            'data-attr': 'workflow-enable-on-sandbox-sender',
            onClick: () => {
                if (confirmed) {
                    return
                }
                confirmed = true
                posthog.capture('workflows sandbox sender enabled anyway', { workflow_id: workflowId, surface })
                onEnable()
            },
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}
