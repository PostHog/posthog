import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OrganizationAI } from './OrgAI'

describe('<OrganizationAI />', () => {
    let patchCount: number
    let releasePatch: ((value: unknown) => void) | null

    beforeEach(() => {
        patchCount = 0
        releasePatch = null

        useMocks({
            patch: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}`]: async () => {
                    patchCount += 1
                    await new Promise((resolve) => {
                        releasePatch = resolve
                    })
                    return [200, { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false }]
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

    it('one click on the third-party-AI toggle fires exactly one PATCH', async () => {
        render(<OrganizationAI />)

        const toggle = screen.getByTestId('organization-ai-enabled')
        await userEvent.click(toggle)

        await waitFor(() => expect(patchCount).toBe(1))
    })

    it('rapid double-click is collapsed to one PATCH by the loading guard', async () => {
        render(<OrganizationAI />)

        const toggle = screen.getByTestId('organization-ai-enabled')

        await userEvent.click(toggle)
        await waitFor(() => expect(patchCount).toBe(1))

        await userEvent.click(toggle)
        expect(patchCount).toBe(1)
    })
})
