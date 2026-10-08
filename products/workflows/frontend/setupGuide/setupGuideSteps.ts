// pinned: analytics property values for the setup guide events - renaming breaks dashboards
export const SETUP_GUIDE_STEP_KEYS = ['channel', 'domain', 'opt-outs', 'email-template', 'first-journey'] as const
export type SetupGuideStepKey = (typeof SETUP_GUIDE_STEP_KEYS)[number]

export interface SetupGuideStep {
    key: SetupGuideStepKey
    done: boolean
}

/** What the guide reads to decide which steps are done. `null` means the value has not loaded yet. */
export interface SetupGuideInputs {
    emailChannels: { verified: boolean }[] | null
    optOutCategoryCount: number | null
    emailTemplateCount: number | null
    hasMessagingWorkflow: boolean | null
}

/**
 * The messaging setup steps, in order. Returns `null` until every input has loaded, so the guide never
 * shows a step as open only because its data is still on the way.
 */
export function deriveSetupGuideSteps(inputs: SetupGuideInputs): SetupGuideStep[] | null {
    const { emailChannels, optOutCategoryCount, emailTemplateCount, hasMessagingWorkflow } = inputs
    if (
        emailChannels === null ||
        optOutCategoryCount === null ||
        emailTemplateCount === null ||
        hasMessagingWorkflow === null
    ) {
        return null
    }
    const done: Record<SetupGuideStepKey, boolean> = {
        channel: emailChannels.length > 0,
        domain: emailChannels.some((channel) => channel.verified),
        'opt-outs': optOutCategoryCount > 0,
        'email-template': emailTemplateCount > 0,
        'first-journey': hasMessagingWorkflow,
    }
    return SETUP_GUIDE_STEP_KEYS.map((key) => ({ key, done: done[key] }))
}

export const SETUP_GUIDE_STEP_LABELS: Record<SetupGuideStepKey, string> = {
    channel: 'Connect an email channel',
    domain: 'Verify your sending domain',
    'opt-outs': 'Add opt-out categories',
    'email-template': 'Design your first email',
    'first-journey': 'Start your first journey',
}

/** The setup tab a step opens. The first journey opens the workflow templates instead, so it has no tab. */
export const SETUP_GUIDE_STEP_TABS: Record<SetupGuideStepKey, 'channels' | 'opt-outs' | 'library' | null> = {
    channel: 'channels',
    domain: 'channels',
    'opt-outs': 'opt-outs',
    'email-template': 'library',
    'first-journey': null,
}
