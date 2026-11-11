import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { WorkflowsOnboardingPath } from '../workflowsSetupGuideLogic'
import { onboardingWizardUrl } from './onboardingWizardSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

const EMAIL_CHANNEL = {
    id: 1,
    kind: 'email',
    display_name: 'hello@mail.example.com',
    icon_url: '',
    created_at: '',
    config: { email: 'hello@mail.example.com', verified: false },
}

const WELCOME_TEMPLATE = {
    id: 'welcome-template',
    name: 'Welcome new users',
    description: 'Send a welcome email after sign-up.',
    scope: 'global',
    actions: [],
    edges: [],
}

const page = (results: unknown[]): { results: unknown[]; count: number; next: null } => ({
    results,
    count: results.length,
    next: null,
})

describe('workflowsOnboardingWizardLogic', () => {
    let logic: ReturnType<typeof workflowsOnboardingWizardLogic.build>

    const setJourneyFirstVariant = (variant: string | undefined): void => {
        featureFlagLogic.actions.setFeatureFlags(
            [],
            variant ? { [FEATURE_FLAGS.WORKFLOWS_WIZARD_JOURNEY_FIRST]: variant } : {}
        )
    }

    const enterWizard = async (path: WorkflowsOnboardingPath): Promise<void> => {
        router.actions.push(onboardingWizardUrl(path))
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).delay(1)
    }

    const continueToTheEnd = async (): Promise<void> => {
        const steps = logic.values.stepKeys.length
        for (let step = logic.values.stepIndex; step < steps; step++) {
            expect(logic.values.continueDisabledReason).toBeNull()
            await expectLogic(logic, () => logic.actions.next()).toFinishAllListeners()
        }
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': page([EMAIL_CHANNEL]),
                '/api/projects/:team_id/integrations': page([EMAIL_CHANNEL]),
                '/api/projects/:team_id/hog_flow_templates/': page([WELCOME_TEMPLATE]),
                '/api/environments/:team_id/hog_flow_templates/': page([WELCOME_TEMPLATE]),
                '/api/projects/:team_id/hog_flows/': page([]),
                '/api/environments/:team_id/hog_flows/': page([]),
                '/api/environments/:team_id/messaging_categories/': page([]),
                '/api/environments/:team_id/messaging_templates/': page([]),
                '/api/projects/:team_id/messaging_templates/': page([]),
            },
            patch: {
                '/api/environments/:team_id/': async ({ request }) => [
                    200,
                    { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as object) },
                ],
            },
        })
        initKeaTests()
        jest.spyOn(posthog, 'getFeatureFlag').mockReturnValue(undefined)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each<[string, WorkflowsOnboardingPath, string | undefined, string[], string]>([
        [
            'the test arm picks the journey before the connected email',
            'messaging',
            'test',
            ['journey', 'channel', 'domain', 'opt-outs', 'sending-rules'],
            'journey',
        ],
        [
            'the test arm shows the broadcast before the connected email',
            'broadcast',
            'test',
            ['broadcast', 'channel', 'domain', 'opt-outs', 'sending-rules'],
            'broadcast',
        ],
        [
            'the control arm sets up email first',
            'messaging',
            'control',
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'journey'],
            'domain',
        ],
        [
            'no flag sets up email first',
            'messaging',
            undefined,
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'journey'],
            'domain',
        ],
        [
            'the control arm sets up the broadcast email first',
            'broadcast',
            'control',
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'broadcast'],
            'domain',
        ],
        ['the test arm leaves automation alone', 'automation', 'test', ['template', 'connect', 'create'], 'template'],
    ])('%s', async (_, path, variant, expectedSteps, landsOn) => {
        setJourneyFirstVariant(variant)
        logic = workflowsOnboardingWizardLogic()
        logic.mount()

        await enterWizard(path)

        expect(logic.values.stepKeys).toEqual(expectedSteps)
        expect(logic.values.currentStep).toBe(landsOn)
    })

    it('opens the journey picked at the first step once the setup steps are done', async () => {
        setJourneyFirstVariant('test')
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
        await enterWizard('messaging')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.continueDisabledReason).toBe('Pick a template or start from scratch')
        expect(logic.values.suggestionsFirst).toBe(false)

        logic.actions.selectTemplate(WELCOME_TEMPLATE.id)
        await continueToTheEnd()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.workflowNew())
        expect(router.values.searchParams).toMatchObject({ templateId: WELCOME_TEMPLATE.id })
    })

    it('keeps the step and the picked journey when a test arm person reloads a later step', async () => {
        setJourneyFirstVariant('test')
        logic = workflowsOnboardingWizardLogic()
        logic.mount()

        router.actions.push(onboardingWizardUrl('messaging', { step: 'domain', template: WELCOME_TEMPLATE.id }))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.currentStep).toBe('domain')
        await continueToTheEnd()

        expect(router.values.searchParams).toMatchObject({ templateId: WELCOME_TEMPLATE.id })
    })

    it('opens the broadcast editor after the setup steps in the test arm', async () => {
        setJourneyFirstVariant('test')
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
        await enterWizard('broadcast')

        await continueToTheEnd()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.broadcastNew())
    })

    it.each<[WorkflowsOnboardingPath, boolean]>([
        ['messaging', true],
        ['broadcast', true],
        ['automation', false],
    ])('records exposure when a person enters the %s wizard: %s', async (path, exposed) => {
        setJourneyFirstVariant('test')
        const recordExposure = jest.mocked(posthog.getFeatureFlag)
        const journeyFirstExposures = (): number =>
            recordExposure.mock.calls.filter(([flag]) => flag === FEATURE_FLAGS.WORKFLOWS_WIZARD_JOURNEY_FIRST).length
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(journeyFirstExposures()).toBe(0)

        await enterWizard(path)

        expect(journeyFirstExposures() > 0).toBe(exposed)
    })
})
