import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OrganizationAITrainingOptOut } from './OrgAITraining'

describe('<OrganizationAITrainingOptOut />', () => {
    let patchCount: number
    let patchPayloads: Array<Record<string, any>>
    // Hold the in-flight PATCH response until we explicitly release it so we
    // can simulate the user clicking again while the first call is still pending.
    let releasePatch: ((value: unknown) => void) | null

    beforeEach(() => {
        patchCount = 0
        patchPayloads = []
        releasePatch = null

        useMocks({
            patch: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}`]: async (req) => {
                    patchCount += 1
                    patchPayloads.push((await req.json()) as Record<string, any>)
                    await new Promise((resolve) => {
                        releasePatch = resolve
                    })
                    return [
                        200,
                        {
                            ...MOCK_DEFAULT_ORGANIZATION,
                            is_ai_training_opted_in: false,
                        },
                    ]
                },
            },
            get: {
                '/api/users/@me': MOCK_DEFAULT_USER,
            },
        })

        initKeaTests()
        userLogic.mount()
        organizationLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_training_opted_in: true,
            is_hipaa: false,
            is_ai_training_locked: false,
        } as any)
    })

    afterEach(async () => {
        // Drain any still-pending PATCH so its loader resolution doesn't bleed
        // into the next test (otherwise jest re-renders into a stale node and
        // queries find multiple elements).
        if (releasePatch) {
            await act(async () => {
                releasePatch?.(undefined)
            })
        }
        cleanup()
    })

    it('a single user click fires exactly one PATCH with the inverted value', async () => {
        render(<OrganizationAITrainingOptOut />)

        const toggle = screen.getByTestId('organization-ai-training-opt-in')
        await userEvent.click(toggle)
        await waitFor(() => expect(patchCount).toBe(1))

        expect(patchPayloads[0]).toEqual({ is_ai_training_opted_in: false })
    })

    it('two sequential clicks (after the first resolves) fire two PATCHes', async () => {
        render(<OrganizationAITrainingOptOut />)

        const toggle = screen.getByTestId('organization-ai-training-opt-in')
        await userEvent.click(toggle)
        await waitFor(() => expect(patchCount).toBe(1))

        await act(async () => {
            releasePatch?.(undefined)
            releasePatch = null
        })

        const toggleAfter = await screen.findByTestId('organization-ai-training-opt-in')
        await userEvent.click(toggleAfter)
        await waitFor(() => expect(patchCount).toBe(2))
    })

    it('double-clicks cannot flip the user back to the original value (the safety property)', async () => {
        // This is the load-bearing invariant: even if the loading guard races
        // and a second click slips through before `currentOrganizationLoading`
        // propagates to the LemonSwitch's `disabled` prop, the *user's intent*
        // is still preserved. Both handler invocations read the same render's
        // `checked` value (closure-captured), so both compute the same `!checked`
        // and PATCH the same value. The net effect on the database is the
        // user's intended toggle direction — never the opposite.
        render(<OrganizationAITrainingOptOut />)

        const toggle = screen.getByTestId('organization-ai-training-opt-in')

        // Fire two clicks synchronously in the same task — a stress case the
        // loading guard alone might not catch. Wrapping in act() lets React
        // batch the resulting renders.
        await act(async () => {
            fireEvent.click(toggle)
            fireEvent.click(toggle)
        })
        // Drain any in-flight PATCH so we can inspect what got sent.
        await act(async () => {
            releasePatch?.(undefined)
            releasePatch = null
        })

        // We don't care here whether the loading guard collapsed the second
        // click — what matters is that every PATCH that did fire carried the
        // user's intent (`false`, the opposite of the initial `checked=true`).
        expect(patchCount).toBeGreaterThanOrEqual(1)
        for (const payload of patchPayloads) {
            expect(payload).toEqual({ is_ai_training_opted_in: false })
        }
    })
})
