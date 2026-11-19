import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { BigAction } from './BigAction'

// The id of the "Welcome email sequence" template shipped in products/workflows/backend/templates.
const WELCOME_EMAIL_TEMPLATE_ID = '019b6f44-f9a3-0000-c4a7-b8050d25d690'

export function CreateWelcomeWorkflowAction({ 'data-attr': dataAttr }: { 'data-attr': string }): JSX.Element {
    return (
        <BigAction
            icon={<IconPlus />}
            onClick={() => router.actions.push(urls.workflowNew(), { templateId: WELCOME_EMAIL_TEMPLATE_ID })}
            data-attr={dataAttr}
        >
            Create the welcome email workflow
        </BigAction>
    )
}
