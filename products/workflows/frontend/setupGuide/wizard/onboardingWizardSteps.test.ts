import { MESSAGING_WIZARD_STEPS, firstOpenStepIndex, requiredConnections } from './onboardingWizardSteps'

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
        ['everything done lands on the last step', { channel: true, domain: true, 'opt-outs': true, journey: true }, 3],
    ])('%s', (_, done, expected) => {
        expect(firstOpenStepIndex(MESSAGING_WIZARD_STEPS, done)).toBe(expected)
    })
})
