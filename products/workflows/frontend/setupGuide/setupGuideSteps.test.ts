import { SetupGuideInputs, deriveSetupGuideSteps } from './setupGuideSteps'

const LOADED: SetupGuideInputs = {
    emailChannels: [],
    optOutCategoryCount: 0,
    emailTemplateCount: 0,
    hasMessagingWorkflow: false,
}

describe('deriveSetupGuideSteps', () => {
    test.each<[string, Partial<SetupGuideInputs>]>([
        ['channels', { emailChannels: null }],
        ['opt-out categories', { optOutCategoryCount: null }],
        ['email templates', { emailTemplateCount: null }],
        ['messaging workflows', { hasMessagingWorkflow: null }],
    ])('is unknown while %s are loading', (_, missing) => {
        expect(deriveSetupGuideSteps({ ...LOADED, ...missing })).toBeNull()
    })

    test.each<[string, Partial<SetupGuideInputs>, string[]]>([
        ['nothing set up', {}, []],
        [
            'an unverified channel completes only the channel step',
            { emailChannels: [{ verified: false }] },
            ['channel'],
        ],
        [
            'one verified channel among several completes the domain step',
            { emailChannels: [{ verified: false }, { verified: true }] },
            ['channel', 'domain'],
        ],
        [
            'everything set up',
            {
                emailChannels: [{ verified: true }],
                optOutCategoryCount: 2,
                emailTemplateCount: 1,
                hasMessagingWorkflow: true,
            },
            ['channel', 'domain', 'opt-outs', 'email-template', 'first-journey'],
        ],
    ])('%s', (_, inputs, expectedDone) => {
        const steps = deriveSetupGuideSteps({ ...LOADED, ...inputs })
        expect(steps?.filter((step) => step.done).map((step) => step.key)).toEqual(expectedDone)
    })
})
