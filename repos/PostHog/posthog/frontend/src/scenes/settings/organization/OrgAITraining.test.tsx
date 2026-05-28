import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
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
                'api/users/@me/': MOCK_DEFAULT_USER,
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
        // into the next test's DOM (otherwise jest re-renders into a stale node
        // and queries find multiple elements).
        if (releasePatch) {
            await act(async () => {
                releasePatch?.(undefined)
            })
        }
        cleanup()
    })

    it('a single user click fires exactly one PATCH', async () => {
        render(<OrganizationAITrainingOptOut />)

        const toggle = screen.getByTestId('organization-ai-training-opt-in')
        await userEvent.click(toggle)
        await waitFor(() => expect(patchCount).toBe(1))

        expect(patchPayloads[0]).toEqual({ is_ai_training_opted_in: false })
    })

    it('rapid double-click while the PATCH is in flight only fires one PATCH (loading guard)', async () => {
        render(<OrganizationAITrainingOptOut />)

        const toggle = screen.getByTestId('organization-ai-training-opt-in')

        // First click — kicks off PATCH that the mock holds open until release.
        await userEvent.click(toggle)
        await waitFor(() => expect(patchCount).toBe(1))

        // Second click while the request is still in flight. The LemonSwitch
        // sets `disabled` from the loading prop, so the click should be a no-op.
        await userEvent.click(toggle)
        expect(patchCount).toBe(1)
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
})
