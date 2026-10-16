import {
    FrequencyCap,
    FrequencyCapPreset,
    MESSAGING_WIZARD_STEPS,
    firstOpenStepIndex,
    frequencyCapToSave,
    requiredConnections,
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

    const unset: FrequencyCap = { maxMessages: null, windowDays: null }
    test.each<[string, FrequencyCap, FrequencyCapPreset | null, FrequencyCap | null]>([
        ['a new setup gets the recommended cap', unset, null, { maxMessages: 1, windowDays: 2 }],
        ['picking no cap on a new setup saves nothing', unset, 'off', null],
        ['a custom cap is kept', { maxMessages: 10, windowDays: 14 }, null, null],
        ['a recommended cap is not saved again', { maxMessages: 1, windowDays: 2 }, 'recommended', null],
        ['picking no cap clears a saved cap', { maxMessages: 3, windowDays: 7 }, 'off', unset],
        [
            'picking a preset replaces a custom cap',
            { maxMessages: 10, windowDays: 14 },
            'weekly',
            { maxMessages: 3, windowDays: 7 },
        ],
    ])('%s', (_, saved, choice, expected) => {
        expect(frequencyCapToSave(saved, choice)).toEqual(expected)
    })
})
