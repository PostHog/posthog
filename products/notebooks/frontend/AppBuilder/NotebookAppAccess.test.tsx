import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NotebookAppAccess } from './NotebookAppAccess'

it('closes access management and clears the previous recipients when the release changes', async () => {
    initKeaTests()
    const admin = {
        ...MOCK_DEFAULT_USER,
        organization: { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Admin },
    }
    useMocks({
        get: {
            '/api/users/@me/': () => [200, admin],
            '/api/projects/:project/notebooks/:notebook/app_view_grants/active/': () => [
                200,
                { results: [], next: null },
            ],
        },
    })
    userLogic.mount()
    userLogic.actions.loadUserSuccess(admin)
    const { rerender } = render(<NotebookAppAccess project="2" shortId="weekly-report" revision={1} />)
    fireEvent.click(screen.getByRole('button', { name: 'App-only access' }))
    await screen.findByText('No active recipients.')
    fireEvent.change(screen.getByLabelText('Member email'), { target: { value: 'recipient@example.com' } })

    rerender(<NotebookAppAccess project="2" shortId="weekly-report" revision={2} />)
    expect(screen.queryByLabelText('Member email')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'App-only access' }))
    await screen.findByText('No active recipients.')
    expect(screen.getByLabelText('Member email')).toHaveValue('')
})
