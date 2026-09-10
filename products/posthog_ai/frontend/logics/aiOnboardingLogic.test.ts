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
    let failNextSeenWrite: boolean

    beforeEach(() => {
        seenWrites = []
        failNextSeenWrite = false
        useMocks({
            patch: {
                '/api/users/@me/product_intro_seen': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    seenWrites.push(body)
                    if (failNextSeenWrite) {
                        failNextSeenWrite = false
                        return [500, { detail: 'the seen write failed' }]
                    }
                    return { [body.product_key]: body.seen }
                },
            },
            get: {
                // The reload after a write has to see it, the way the real endpoint does. Without this the
                // persisted flag never flips and every dismissal looks like a first write.
                '/api/users/@me/': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_USER,
                        has_seen_product_intro_for: Object.fromEntries(
                            seenWrites.map(({ product_key, seen }) => [product_key, seen])
                        ),
                    },
                ],
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

    // Persisting only on the way out greeted people again on their next visit, because closing the tab,
    // following a link, or reloading never reaches a dismissal. A replay has to stay silent: it opens the
    // takeover on surfaces that never showed it, so writing there swallows the one real showing.
    // The key matters too — one the open check doesn't read reopens the takeover forever.
    it.each([
        ['opens', false, [{ product_key: POSTHOG_AI_ONBOARDING_SEEN_KEY, seen: true }]],
        ['is replayed', true, []],
    ])('records the seen flag when the takeover %s', async (_name, isReplay, expected) => {
        mountLogic()
        userLogic.findMounted()?.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER })

        await expectLogic(logic, () => {
            logic.actions.openOnboarding(isReplay)
        }).toFinishAllListeners()

        expect(seenWrites).toEqual(expected)
    })

    // Both the open and the dismissal mark the takeover seen, so the persisted flag is what stops the
    // second one from writing again and dragging another full user reload behind it.
    it('records the seen flag once across an open and a dismissal', async () => {
        mountLogic()
        userLogic.findMounted()?.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER })

        await expectLogic(logic, () => {
            logic.actions.openOnboarding()
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.closeOnboarding()
        }).toFinishAllListeners()

        expect(seenWrites).toEqual([{ product_key: POSTHOG_AI_ONBOARDING_SEEN_KEY, seen: true }])
    })

    // A replay opens the takeover on a surface that never showed it, so it has to write nothing on the way
    // out as well as on open. Otherwise dismissing, finishing, or answering a prompt after a replay persists
    // the flag and swallows the user's one real first-run showing on the new surface.
    it.each([
        ['dismissed', () => logic.actions.closeOnboarding()],
        ['finished', () => logic.actions.finishOnboarding()],
        ['answered with a starter prompt', () => logic.actions.selectStarterPrompt('Audit my event tracking.')],
    ])('writes nothing when a replay is %s', async (_name, exit) => {
        mountLogic()
        userLogic.findMounted()?.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER })

        await expectLogic(logic, () => {
            logic.actions.openOnboarding(true)
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            exit()
        }).toFinishAllListeners()

        expect(seenWrites).toHaveLength(0)
        // The session flag has to stay clear as well, or the real surface cannot open the takeover for the
        // rest of the session. Guarding inside `markOnboardingSeen` would pass the check above but fail here.
        expect(logic.values.hasSeenOnboarding).toBe(false)
    })

    // A failed write must not stop a later one from persisting the flag, or a transient error means the
    // takeover comes back for good. An earlier guard latched before the request and never cleared.
    it('retries the seen write on dismissal after the open-time write fails', async () => {
        mountLogic()
        userLogic.findMounted()?.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER })
        failNextSeenWrite = true

        await expectLogic(logic, () => {
            logic.actions.openOnboarding()
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.closeOnboarding()
        }).toFinishAllListeners()

        expect(seenWrites).toHaveLength(2)
    })

    // `/api/users/` rejects writes from an impersonated session, so persisting the flag can only
    // fail. The takeover still has to close, or every dismissal re-opens it over the composer.
    it('closes without writing the seen flag while impersonating', async () => {
        mountLogic()
        userLogic.findMounted()?.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_impersonated: true })

        await expectLogic(logic, () => {
            logic.actions.openOnboarding()
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
