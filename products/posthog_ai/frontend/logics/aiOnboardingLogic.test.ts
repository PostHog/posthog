import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { OrganizationType, TeamType } from '~/types'

import { DEFAULT_STARTER_PROMPTS, EMPTY_PROJECT_STARTER_PROMPTS } from '../components/onboarding/onboardingSteps'
import { POSTHOG_AI_ONBOARDING_SEEN_KEY, aiOnboardingLogic } from './aiOnboardingLogic'
import { composerSeedLogic } from './composerSeedLogic'

describe('aiOnboardingLogic', () => {
    let logic: ReturnType<typeof aiOnboardingLogic.build>
    let seedLogic: ReturnType<typeof composerSeedLogic.build>
    let seenWrites: Record<string, any>[]

    beforeEach(() => {
        seenWrites = []
        useMocks({
            patch: {
                '/api/users/@me/product_intro_seen': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    seenWrites.push(body)
                    return { [body.product_key]: body.seen }
                },
            },
        })
    })

    function mountLogic({
        ingestedEvent = true,
        aiApproved = true,
    }: { ingestedEvent?: boolean; aiApproved?: boolean } = {}): void {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, ingested_event: ingestedEvent } as TeamType, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: aiApproved,
        } as OrganizationType)
        logic = aiOnboardingLogic()
        logic.mount()
        seedLogic = composerSeedLogic({})
        seedLogic.mount()
    }

    afterEach(() => {
        seedLogic?.unmount()
        logic?.unmount()
    })

    // A brand-new org has no events, so the default prompts would all come back empty. Inverting this
    // selector is the difference between an onboarding that works on a fresh project and three dead ends.
    it.each([
        [true, DEFAULT_STARTER_PROMPTS],
        [false, EMPTY_PROJECT_STARTER_PROMPTS],
    ])('offers the right starter prompts when ingested_event is %s', (ingestedEvent, expected) => {
        mountLogic({ ingestedEvent })

        expect(logic.values.starterPrompts).toEqual(expected)
    })

    // Auto-submitting without org AI-data-processing approval pops the consent flow on top of the
    // onboarding and the run never starts. Without approval the prompt must only prefill the composer.
    it.each([
        [true, true],
        [false, false],
    ])('sets autoSubmit to %s when AI data processing approval is %s', async (aiApproved, expectedAutoSubmit) => {
        mountLogic({ aiApproved })

        await expectLogic(logic, () => {
            logic.actions.selectStarterPrompt('Audit my event tracking.')
        }).toFinishAllListeners()

        expect(seedLogic.values.seed).toEqual({
            prompt: 'Audit my event tracking.',
            autoSubmit: expectedAutoSubmit,
        })
    })

    // The takeover reopens forever if the dismissal names a key the open check doesn't read. It also has to
    // stay a single-key write: sending the whole map back is what let two tabs drop each other's intro.
    it('records the seen flag against the onboarding key alone', async () => {
        mountLogic()
        userLogic
            .findMounted()
            ?.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, has_seen_product_intro_for: { session_replay: true } })

        await expectLogic(logic, () => {
            logic.actions.closeOnboarding()
        }).toFinishAllListeners()

        expect(seenWrites).toEqual([{ product_key: POSTHOG_AI_ONBOARDING_SEEN_KEY, seen: true }])
    })

    // `/api/users/` rejects writes from an impersonated session, so persisting the flag can only
    // fail. The takeover still has to close, or every dismissal re-opens it over the composer.
    it('closes without writing the seen flag while impersonating', async () => {
        mountLogic()
        userLogic.findMounted()?.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_impersonated: true })

        await expectLogic(logic, () => {
            logic.actions.closeOnboarding()
        }).toFinishAllListeners()

        expect(seenWrites).toHaveLength(0)
        expect(logic.values.hasSeenOnboarding).toBe(true)
        expect(logic.values.isOpen).toBe(false)
    })

    // Which step a user bails on is the segment signal the onboarding exists to collect. Stepping back and
    // forth must not inflate it, or the per-step funnel stops meaning anything.
    it('reports each step view only once per opening', async () => {
        mountLogic()
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

        try {
            await expectLogic(logic, () => {
                logic.actions.openOnboarding()
                logic.actions.setStepIndex(1)
                logic.actions.setStepIndex(0)
                logic.actions.setStepIndex(1)
            }).toFinishAllListeners()

            const stepViews = captureSpy.mock.calls.filter((call) => call[0] === 'posthog ai onboarding step viewed')
            expect(stepViews).toHaveLength(1)
            expect(stepViews[0][1]).toEqual(expect.objectContaining({ step_key: 'delegate', step_index: 1 }))
        } finally {
            captureSpy.mockRestore()
        }
    })
})
