import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { WorkflowsConfig } from '~/types'

import {
    MAX_FREQUENCY_CAP_MESSAGES,
    MAX_FREQUENCY_CAP_WINDOW_DAYS,
    frequencyCapFieldError,
} from '../../scenes/settings/frequencyCap'
import type { HogFlowAction } from '../../Workflows/hogflows/types'
import type { WorkflowsOnboardingPath } from '../workflowsSetupGuideLogic'

// pinned: URL values and analytics property values for the wizard events - renaming breaks links and dashboards
export const MESSAGING_WIZARD_STEPS = ['channel', 'domain', 'opt-outs', 'sending-rules', 'journey'] as const
export const AUTOMATION_WIZARD_STEPS = ['template', 'connect', 'create'] as const
export const BROADCAST_WIZARD_STEPS = ['channel', 'domain', 'opt-outs', 'sending-rules', 'broadcast'] as const
export const PUSH_WIZARD_STEP = 'push' as const
export type WizardStepKey =
    | (typeof MESSAGING_WIZARD_STEPS)[number]
    | (typeof AUTOMATION_WIZARD_STEPS)[number]
    | (typeof BROADCAST_WIZARD_STEPS)[number]
    | typeof PUSH_WIZARD_STEP

// pinned: URL path and search params of the wizard - renaming breaks the Slack sign-in return link
export const ONBOARDING_WIZARD_TAB = 'onboarding'
/** The `template` value for starting from an empty workflow instead of a template. */
export const BLANK_START_ID = 'blank'
/** The `template_id` the finished event reports when a data suggestion created the workflow. */
export const DATA_SUGGESTION_START_ID = 'data_suggestion'

// pinned: URL value and analytics property value of the wizard events - renaming breaks dashboards
export const WIZARD_ENTRIES = [
    'path_choice',
    'messaging_setup_guide',
    'automation_empty_state',
    'automation_banner',
    'broadcasts_empty_state',
] as const
export type WizardEntry = (typeof WIZARD_ENTRIES)[number]

export function onboardingWizardUrl(
    path: WorkflowsOnboardingPath,
    params: { step?: WizardStepKey; template?: string; entry?: WizardEntry } = {}
): string {
    return combineUrl(urls.workflows(ONBOARDING_WIZARD_TAB), { path, ...params }).url
}

export const WIZARD_STEPS: Record<WorkflowsOnboardingPath, readonly WizardStepKey[]> = {
    messaging: MESSAGING_WIZARD_STEPS,
    automation: AUTOMATION_WIZARD_STEPS,
    broadcast: BROADCAST_WIZARD_STEPS,
}

/** The steps of one path. Messaging asks about push before the first journey when the project can send push.
 * Broadcasts only send email, so that path never asks. */
export function wizardSteps(path: WorkflowsOnboardingPath, pushEnabled: boolean): readonly WizardStepKey[] {
    const steps = WIZARD_STEPS[path]
    if (path !== 'messaging' || !pushEnabled) {
        return steps
    }
    const journeyIndex = steps.indexOf('journey')
    return [...steps.slice(0, journeyIndex), PUSH_WIZARD_STEP, ...steps.slice(journeyIndex)]
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
        description: 'Email goes out from your own domain. Add the address that people see in their inbox.',
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
    'sending-rules': {
        label: 'Sending rules',
        title: 'Choose how often people hear from you',
        description:
            'These rules apply to every workflow and broadcast in this project. The defaults keep people from getting too many marketing emails. You can change them later in Messaging settings.',
        optional: false,
    },
    push: {
        label: 'Push',
        title: 'Send push notifications too?',
        description:
            'Reach people on their phones as well as in their inbox. You can also set this up later in Messaging.',
        optional: true,
    },
    journey: {
        label: 'First journey',
        title: 'Pick your first journey',
        description:
            'Start from a template or from scratch. It opens in the editor, where you change the trigger and the emails and save it as a draft. Nothing sends until you launch it.',
        optional: false,
    },
    broadcast: {
        label: 'First broadcast',
        title: 'Write your first broadcast',
        description:
            'It opens the broadcast editor. You pick a sender and who gets it, write the email, and send it now or schedule it. Nothing sends until you confirm.',
        optional: false,
    },
    template: {
        label: 'Template',
        title: 'What do you want to automate?',
        description: 'Pick a template, or start from scratch. You can change every step later.',
        optional: false,
    },
    connect: {
        label: 'Connections',
        title: 'Connect the tools it uses',
        description: 'Some steps post to other tools. Connect them now, or later from the workflow.',
        optional: true,
    },
    create: {
        label: 'Review',
        title: 'Review and open',
        description: 'It opens in the editor, where you save it as a draft. Nothing runs until you launch it.',
        optional: false,
    },
}

export interface FrequencyCap {
    maxMessages: number | null
    windowDays: number | null
}

export const RECOMMENDED_FREQUENCY_CAP: FrequencyCap = { maxMessages: 1, windowDays: 2 }
const NO_FREQUENCY_CAP: FrequencyCap = { maxMessages: null, windowDays: null }

// pinned: analytics property values for the sending rules step - renaming breaks dashboards
export type FrequencyCapChoice = 'recommended' | 'custom' | 'off'

function sameFrequencyCap(a: FrequencyCap, b: FrequencyCap): boolean {
    return a.maxMessages === b.maxMessages && a.windowDays === b.windowDays
}

/** The choice the step starts on. An unset cap starts on the recommended cap when the person can save it. */
export function initialFrequencyCapChoice(saved: FrequencyCap, canEdit: boolean): FrequencyCapChoice {
    if (saved.maxMessages === null || saved.windowDays === null) {
        return canEdit ? 'recommended' : 'off'
    }
    return sameFrequencyCap(saved, RECOMMENDED_FREQUENCY_CAP) ? 'recommended' : 'custom'
}

export function chosenFrequencyCap(choice: FrequencyCapChoice, custom: FrequencyCap): FrequencyCap {
    return choice === 'recommended' ? RECOMMENDED_FREQUENCY_CAP : choice === 'off' ? NO_FREQUENCY_CAP : custom
}

// Both fields are required here, because "No cap" is its own choice in the wizard.
export function customFrequencyCapError(cap: FrequencyCap): string | null {
    if (cap.maxMessages === null || cap.windowDays === null) {
        return 'Fill in both fields'
    }
    return (
        frequencyCapFieldError(cap.maxMessages, cap.windowDays, MAX_FREQUENCY_CAP_MESSAGES) ??
        frequencyCapFieldError(cap.windowDays, cap.maxMessages, MAX_FREQUENCY_CAP_WINDOW_DAYS) ??
        null
    )
}

/** What the sending rules step saves when the person continues, or null when nothing changes. */
export function sendingRulesToSave(
    saved: FrequencyCap & { engagementEvents: boolean },
    cap: FrequencyCap,
    engagementEvents: boolean,
    canEdit: boolean
): WorkflowsConfig | null {
    // The backend lets only project admins change any part of workflows_config.
    if (!canEdit) {
        return null
    }
    const setCap = !sameFrequencyCap(saved, cap)
    if (!setCap && engagementEvents === saved.engagementEvents) {
        return null
    }
    return {
        capture_workflows_engagement_events: engagementEvents,
        ...(setCap
            ? {
                  marketing_frequency_cap_max_messages: cap.maxMessages,
                  marketing_frequency_cap_window_days: cap.windowDays,
              }
            : {}),
    }
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
