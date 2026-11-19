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
    LemonDialog.open({
        title: 'Enable on the PostHog test sender?',
        description:
            'This workflow sends email from the PostHog test sender. Only verified members of your organization receive it. Everyone else is skipped until you set up your sending domain.',
        primaryButton: {
            children: 'Enable anyway',
            'data-attr': 'workflow-enable-on-sandbox-sender',
            onClick: () => {
                posthog.capture('workflows sandbox sender enabled anyway', { workflow_id: workflowId, surface })
                onEnable()
            },
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}
