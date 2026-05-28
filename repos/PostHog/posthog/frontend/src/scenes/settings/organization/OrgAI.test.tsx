import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OrganizationAI } from './OrgAI'

describe('<OrganizationAI />', () => {
    let patchCount: number
    let patchPayloads: Array<Record<string, any>>
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
                    return [200, { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false }]
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
            is_ai_data_processing_approved: true,
        } as any)
    })

    afterEach(async () => {
        if (releasePatch) {
            await act(async () => {
                releasePatch?.(undefined)
            })
        }
        cleanup()
    })

    it('one click on the third-party-AI toggle fires exactly one PATCH with the inverted value', async () => {
        render(<OrganizationAI />)

        const toggle = screen.getByTestId('organization-ai-enabled')
        await userEvent.click(toggle)

        await waitFor(() => expect(patchCount).toBe(1))
        expect(patchPayloads[0]).toEqual({ is_ai_data_processing_approved: false })
    })

    it('double-clicks cannot flip the user back to the original value', async () => {
        render(<OrganizationAI />)

        const toggle = screen.getByTestId('organization-ai-enabled')

        await act(async () => {
            fireEvent.click(toggle)
            fireEvent.click(toggle)
        })
        await act(async () => {
            releasePatch?.(undefined)
            releasePatch = null
        })

        // Every PATCH that fired must carry the user's intent (the inverse of
        // the initial `checked=true`). Whether the loading guard fully blocked
        // the second click or not is an implementation detail; the load-bearing
        // invariant is that the database can never end up at the *opposite* of
        // the user's intent because `checked` is closure-captured per render.
        expect(patchCount).toBeGreaterThanOrEqual(1)
        for (const payload of patchPayloads) {
            expect(payload).toEqual({ is_ai_data_processing_approved: false })
        }
    })
})
