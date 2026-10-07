import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { HogFlowAction } from '../../Workflows/hogflows/types'
import type { WorkflowsOnboardingPath } from '../workflowsSetupGuideLogic'

// pinned: URL values and analytics property values for the wizard events - renaming breaks links and dashboards
export const MESSAGING_WIZARD_STEPS = ['channel', 'domain', 'opt-outs', 'journey'] as const
export const AUTOMATION_WIZARD_STEPS = ['template', 'connect', 'create'] as const
export type WizardStepKey = (typeof MESSAGING_WIZARD_STEPS)[number] | (typeof AUTOMATION_WIZARD_STEPS)[number]

// pinned: URL path and search params of the wizard - renaming breaks the Slack sign-in return link
export const ONBOARDING_WIZARD_TAB = 'onboarding'

export function onboardingWizardUrl(
    path: WorkflowsOnboardingPath,
    params: { step?: WizardStepKey; template?: string } = {}
): string {
    return combineUrl(urls.workflows(ONBOARDING_WIZARD_TAB), { path, ...params }).url
}

export const WIZARD_STEPS: Record<WorkflowsOnboardingPath, readonly WizardStepKey[]> = {
    messaging: MESSAGING_WIZARD_STEPS,
    automation: AUTOMATION_WIZARD_STEPS,
}

export interface WizardStepCopy {
    label: string
    title: string
    description: string
    /** An optional step can be skipped, so it never blocks the person from finishing. */
    optional: boolean
}

export const WIZARD_STEP_COPY: Record<WizardStepKey, WizardStepCopy> = {
    channel: {
        label: 'Email channel',
        title: 'Connect the email address you send from',
        description: 'Workflows send email from your own domain. Add the address that people see in their inbox.',
        optional: false,
    },
    domain: {
        label: 'Domain',
        title: 'Verify your sending domain',
        description:
            'Add a few DNS records, so mailbox providers trust your email. Verification can take up to an hour, so you can continue and come back later.',
        optional: true,
    },
    'opt-outs': {
        label: 'Opt-outs',
        title: 'Let people choose what they get',
        description:
            'Opt-out categories let people unsubscribe from one kind of message, such as product updates, and keep the rest. Every email has an unsubscribe link either way.',
        optional: true,
    },
    journey: {
        label: 'First journey',
        title: 'Pick your first journey',
        description:
            'Start from a template. We create a draft, so you can change the trigger and the emails before anything sends.',
        optional: false,
    },
    template: {
        label: 'Template',
        title: 'What do you want to automate?',
        description: 'Pick a template to start from. You can change every step later.',
        optional: false,
    },
    connect: {
        label: 'Connections',
        title: 'Connect the tools it uses',
        description: 'Some steps post to other tools. Connect them now, or later from the workflow.',
        optional: true,
    },
    create: {
        label: 'Create',
        title: 'Review and create',
        description: 'We create a draft workflow. Nothing runs until you launch it.',
        optional: false,
    },
}

// pinned: integration kinds - these are the `kind` values the integrations API returns
export type WizardConnection = 'slack'

const CONNECTION_BY_STEP_TEMPLATE: Record<string, WizardConnection> = {
    'template-slack': 'slack',
}

/** The integrations a workflow needs before its steps can run, in the order they first appear. */
export function requiredConnections(actions: Pick<HogFlowAction, 'config'>[]): WizardConnection[] {
    const needed: WizardConnection[] = []
    for (const action of actions) {
        const templateId = (action.config as { template_id?: string } | undefined)?.template_id
        const connection = templateId ? CONNECTION_BY_STEP_TEMPLATE[templateId] : undefined
        if (connection && !needed.includes(connection)) {
            needed.push(connection)
        }
    }
    return needed
}

/** Where a returning person resumes: the first step that is not done yet, or the last step. */
export function firstOpenStepIndex(
    steps: readonly WizardStepKey[],
    done: Partial<Record<WizardStepKey, boolean>>
): number {
    const index = steps.findIndex((step) => !done[step])
    return index === -1 ? steps.length - 1 : index
}
