import {
    MESSAGING_WIZARD_STEPS,
    customFrequencyCapError,
    firstOpenStepIndex,
    initialFrequencyCapChoice,
    requiredConnections,
    sendingRulesToSave,
    wizardSteps,
} from './onboardingWizardSteps'

describe('onboardingWizardSteps', () => {
    test.each<[string, (string | undefined)[], string[]]>([
        ['email only needs nothing', ['template-email'], []],
        ['a slack step needs slack', ['template-email', 'template-slack'], ['slack']],
        ['two slack steps need slack once', ['template-slack', 'template-slack'], ['slack']],
        ['a webhook and a step without a template need nothing', ['template-webhook', undefined], []],
    ])('%s', (_, templateIds, expected) => {
        const actions = templateIds.map((template_id) => ({ config: template_id ? { template_id } : {} }) as any)
        expect(requiredConnections(actions)).toEqual(expected)
    })

    test.each<[string, Record<string, boolean>, number]>([
        ['a new project starts at the channel', {}, 0],
        ['a connected channel starts at the domain', { channel: true }, 1],
        ['an unverified domain stays open even when later steps are done', { channel: true, 'opt-outs': true }, 1],
        [
            'everything done lands on the last step',
            { channel: true, domain: true, 'opt-outs': true, 'sending-rules': true, journey: true },
            4,
        ],
        ['an unset frequency cap stops before the journey', { channel: true, domain: true, 'opt-outs': true }, 3],
    ])('%s', (_, done, expected) => {
        expect(firstOpenStepIndex(MESSAGING_WIZARD_STEPS, done)).toBe(expected)
    })

    test.each<[string, 'messaging' | 'automation' | 'broadcast', boolean, string[]]>([
        [
            'messaging asks about push before the journey',
            'messaging',
            true,
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'push', 'journey'],
        ],
        [
            'messaging without push keeps the email steps',
            'messaging',
            false,
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'journey'],
        ],
        ['automation never asks about push', 'automation', true, ['template', 'connect', 'create']],
        [
            'broadcasts send email only, so they never ask about push',
            'broadcast',
            true,
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'broadcast'],
        ],
    ])('%s', (_, path, pushEnabled, expected) => {
        expect(wizardSteps(path, pushEnabled)).toEqual(expected)
    })

    const unset = { maxMessages: null, windowDays: null }
    test.each<[string, Parameters<typeof initialFrequencyCapChoice>[0], boolean, string]>([
        ['a new setup starts on the recommended cap', unset, true, 'recommended'],
        ['a non-admin sees an unset cap as no cap', unset, false, 'off'],
        ['a saved recommended cap starts on recommended', { maxMessages: 1, windowDays: 2 }, true, 'recommended'],
        ['a saved custom cap starts on custom', { maxMessages: 3, windowDays: 5 }, true, 'custom'],
    ])('%s', (_, saved, canEdit, expected) => {
        expect(initialFrequencyCapChoice(saved, canEdit)).toBe(expected)
    })

    test.each<[string, Parameters<typeof customFrequencyCapError>[0], boolean]>([
        ['an empty field blocks a custom cap', { maxMessages: 3, windowDays: null }, true],
        ['a window above 30 days blocks a custom cap', { maxMessages: 3, windowDays: 31 }, true],
        ['a valid custom cap passes', { maxMessages: 3, windowDays: 5 }, false],
    ])('%s', (_, cap, blocked) => {
        expect(customFrequencyCapError(cap) !== null).toBe(blocked)
    })

    const saved = { ...unset, engagementEvents: false }
    test.each<[string, Parameters<typeof sendingRulesToSave>, ReturnType<typeof sendingRulesToSave>]>([
        [
            'a new setup saves the recommended cap and engagement events',
            [saved, { maxMessages: 1, windowDays: 2 }, true, true],
            {
                capture_workflows_engagement_events: true,
                marketing_frequency_cap_max_messages: 1,
                marketing_frequency_cap_window_days: 2,
            },
        ],
        [
            'an unchanged custom cap is not saved again',
            [{ maxMessages: 3, windowDays: 5, engagementEvents: true }, { maxMessages: 3, windowDays: 5 }, true, true],
            null,
        ],
        [
            'no cap clears a saved cap',
            [{ maxMessages: 3, windowDays: 5, engagementEvents: true }, unset, true, true],
            {
                capture_workflows_engagement_events: true,
                marketing_frequency_cap_max_messages: null,
                marketing_frequency_cap_window_days: null,
            },
        ],
        ['a non-admin saves nothing', [saved, { maxMessages: 1, windowDays: 2 }, true, false], null],
    ])('%s', (_, args, expected) => {
        expect(sendingRulesToSave(...args)).toEqual(expected)
    })
})
