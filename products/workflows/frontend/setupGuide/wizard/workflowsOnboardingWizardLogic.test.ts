import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo, Mocks } from '~/mocks/utils'
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

    const BROADCAST_WIZARD = onboardingWizardUrl('broadcast')

    it.each<[string, WorkflowsOnboardingPath, string | undefined, string[], string, string]>([
        [
            'the test arm picks the journey before the connected email',
            'messaging',
            'test',
            ['journey', 'channel', 'domain', 'opt-outs', 'sending-rules'],
            'journey',
            BROADCAST_WIZARD,
        ],
        [
            'the test arm shows the broadcast before the connected email',
            'broadcast',
            'test',
            ['broadcast', 'channel', 'domain', 'opt-outs', 'sending-rules'],
            'broadcast',
            BROADCAST_WIZARD,
        ],
        [
            'the control arm sets up email first',
            'messaging',
            'control',
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'journey'],
            'domain',
            urls.broadcastNew(),
        ],
        [
            'no flag sets up email first',
            'messaging',
            undefined,
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'journey'],
            'domain',
            urls.broadcastNew(),
        ],
        [
            'the control arm sets up the broadcast email first',
            'broadcast',
            'control',
            ['channel', 'domain', 'opt-outs', 'sending-rules', 'broadcast'],
            'domain',
            urls.broadcastNew(),
        ],
        [
            'the test arm leaves automation alone',
            'automation',
            'test',
            ['template', 'connect', 'create'],
            'template',
            urls.broadcastNew(),
        ],
    ])('%s', async (_, path, variant, expectedSteps, landsOn, broadcastLink) => {
        setJourneyFirstVariant(variant)
        logic = workflowsOnboardingWizardLogic()
        logic.mount()

        await enterWizard(path)

        expect(logic.values.stepKeys).toEqual(expectedSteps)
        expect(logic.values.currentStep).toBe(landsOn)
        expect(logic.values.broadcastLinkUrl).toBe(broadcastLink)
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

    it.each<[string, string | undefined, string]>([
        ['keeps a later step when the journey is picked', WELCOME_TEMPLATE.id, 'domain'],
        ['sends a resume without a picked journey back to the pick', undefined, 'journey'],
    ])('%s when a test arm person reloads it', async (_, template, landsOn) => {
        setJourneyFirstVariant('test')
        logic = workflowsOnboardingWizardLogic()
        logic.mount()

        router.actions.push(onboardingWizardUrl('messaging', { step: 'domain', template }))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.currentStep).toBe(landsOn)
        if (!template) {
            logic.actions.selectTemplate(WELCOME_TEMPLATE.id)
        }
        await continueToTheEnd()

        expect(router.values.searchParams).toMatchObject({ templateId: WELCOME_TEMPLATE.id })
    })

    it('keeps the arm for the run when the flags change mid-run', async () => {
        setJourneyFirstVariant('test')
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
        await enterWizard('messaging')
        logic.actions.selectTemplate(WELCOME_TEMPLATE.id)
        await expectLogic(logic, () => logic.actions.next()).toFinishAllListeners()

        setJourneyFirstVariant('control')
        await expectLogic(logic, () => logic.actions.next()).toFinishAllListeners()

        expect(logic.values.stepKeys).toEqual(['journey', 'channel', 'domain', 'opt-outs', 'sending-rules'])
        expect(logic.values.currentStep).toBe('domain')

        router.actions.push(onboardingWizardUrl('messaging', { step: 'channel', template: WELCOME_TEMPLATE.id }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.stepKeys).toEqual(['journey', 'channel', 'domain', 'opt-outs', 'sending-rules'])
        expect(logic.values.currentStep).toBe('channel')
    })

    it('stays on the sending rules when they fail to save at the end of the test arm', async () => {
        useMocks({ patch: { '/api/environments/:team_id/': () => [500, { detail: 'Something went wrong' }] } })
        setJourneyFirstVariant('test')
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
        await enterWizard('messaging')
        logic.actions.selectTemplate(WELCOME_TEMPLATE.id)

        await continueToTheEnd()
        await expectLogic(teamLogic).toFinishAllListeners()

        expect(logic.values.currentStep).toBe('sending-rules')
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.workflows('onboarding'))
    })

    function heldTeamSave(): { mocks: Mocks; releaseSave: () => void } {
        let releaseSave: () => void = () => {}
        const saveHeld = new Promise<void>((resolve) => {
            releaseSave = resolve
        })
        const mocks: Mocks = {
            patch: {
                '/api/environments/:team_id/': async ({ request }: MockResolverInfo) => {
                    const body = (await request.json()) as object
                    if ('workflows_config' in body) {
                        await saveHeld
                    }
                    return [200, { ...MOCK_DEFAULT_TEAM, ...body }]
                },
            },
        }
        return { mocks, releaseSave }
    }

    async function reachSendingRules(variant: string = 'test'): Promise<void> {
        setJourneyFirstVariant(variant)
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
        await enterWizard('messaging')
        logic.actions.selectTemplate(WELCOME_TEMPLATE.id)
        while (logic.values.currentStep !== 'sending-rules') {
            await expectLogic(logic, () => logic.actions.next()).toFinishAllListeners()
        }
    }

    it.each<[string, string, string | null, string, string, string]>([
        [
            'the test arm locks the sending rules while they save, then opens the pick',
            'test',
            'Saving your sending rules',
            'sending-rules',
            'sending-rules',
            urls.workflowNew(),
        ],
        [
            'the control arm keeps the sending rules open and moves on while they save',
            'control',
            null,
            'journey',
            'journey',
            urls.workflows('onboarding'),
        ],
    ])('%s', async (_, variant, lockedReason, stepWhileSaving, stepAfterSave, pathnameAfterSave) => {
        const { mocks, releaseSave } = heldTeamSave()
        useMocks(mocks)
        await reachSendingRules(variant)

        logic.actions.next()
        expect(logic.values.sendingRulesDisabledReason).toBe(lockedReason)
        expect(logic.values.currentStep).toBe(stepWhileSaving)
        releaseSave()
        await expectLogic(teamLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sendingRulesDisabledReason).toBeNull()
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(pathnameAfterSave)
        expect(logic.values.currentStep).toBe(stepAfterSave)
    })

    it('stays on the sending rules when another team save returns during their save', async () => {
        const { mocks, releaseSave } = heldTeamSave()
        useMocks(mocks)
        await reachSendingRules()

        logic.actions.next()
        teamLogic.actions.updateCurrentTeam({ timezone: 'Europe/Berlin' })
        await waitFor(() => expect(teamLogic.values.currentTeam?.timezone).toBe('Europe/Berlin'))
        releaseSave()
        await expectLogic(teamLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentStep).toBe('sending-rules')
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.workflows('onboarding'))
    })

    it.each<[string, () => void, string]>([
        ['goes back a step', () => logic.actions.back(), 'opt-outs'],
        ['opens another wizard', () => router.actions.push(onboardingWizardUrl('broadcast')), 'broadcast'],
    ])('stays in the wizard when a person %s while the sending rules save', async (_, leave, landsOn) => {
        const { mocks, releaseSave } = heldTeamSave()
        useMocks(mocks)
        await reachSendingRules()

        logic.actions.next()
        leave()
        releaseSave()
        await expectLogic(teamLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentStep).toBe(landsOn)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.workflows('onboarding'))
    })

    it('opens the broadcast editor after the setup steps in the test arm', async () => {
        setJourneyFirstVariant('test')
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
        await enterWizard('broadcast')

        await continueToTheEnd()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.broadcastNew())
    })

    it.each<[WorkflowsOnboardingPath, string, boolean, boolean]>([
        ['messaging', 'test', true, true],
        ['messaging', 'control', true, false],
        ['broadcast', 'test', true, true],
        ['broadcast', 'control', true, false],
        ['automation', 'test', false, false],
    ])(
        'records exposure when a person enters the %s wizard in the %s arm: %s',
        async (path, variant, exposed, journeyFirst) => {
            setJourneyFirstVariant(variant)
            const recordExposure = jest.mocked(posthog.getFeatureFlag)
            const journeyFirstExposures = (): number =>
                recordExposure.mock.calls.filter(([flag]) => flag === FEATURE_FLAGS.WORKFLOWS_WIZARD_JOURNEY_FIRST)
                    .length
            logic = workflowsOnboardingWizardLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(journeyFirstExposures()).toBe(0)

            await enterWizard(path)

            expect(journeyFirstExposures() > 0).toBe(exposed)
            expect(logic.values.journeyFirst).toBe(journeyFirst)
        }
    )
})
