import { LemonDialog } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { AEOSetupContextApi } from 'products/web_analytics/frontend/generated/api.schemas'

export const openRestartSetupDialog = (context: AEOSetupContextApi | null, onConfirm: () => void): void => {
    const prompts = (context?.active_prompts ?? 0) + (context?.paused_prompts ?? 0)
    const site = context?.own_domains[0]
    LemonDialog.open({
        title: 'Start again with another website?',
        description: (
            <p className="m-0">
                {prompts + (context?.keywords ?? 0) > 0
                    ? `This removes the ${pluralize(prompts, 'prompt')} and ${pluralize(context?.keywords ?? 0, 'keyword')} PostHog set up${site ? ` for ${site}` : ''}, so it can set up your site again from scratch.`
                    : `PostHog sets up your site again from scratch${site ? `, starting from ${site}` : ''}.`}{' '}
                Answers already collected stay in your history, and engine settings don't change.
            </p>
        ),
        primaryButton: {
            children: 'Start again',
            status: 'danger',
            onClick: onConfirm,
            'data-attr': 'ai-visibility-setup-restart-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
