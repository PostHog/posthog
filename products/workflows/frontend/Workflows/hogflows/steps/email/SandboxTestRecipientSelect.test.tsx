import '@testing-library/jest-dom'

import { render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { membersLogic } from '~/models/membersLogic'
import { initKeaTests } from '~/test/init'

import { SandboxTestRecipientSelect } from './SandboxTestRecipientSelect'

function member(uuid: string, firstName: string, verified: boolean): Record<string, unknown> {
    return {
        id: `membership-${uuid}`,
        level: 1,
        joined_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        user: {
            id: uuid.length,
            uuid,
            distinct_id: uuid,
            first_name: firstName,
            email: `${firstName.toLowerCase()}@example.com`,
            is_email_verified: verified,
        },
    }
}

async function renderSelect(value: string): Promise<jest.Mock> {
    const onChange = jest.fn()
    render(
        <Provider>
            <SandboxTestRecipientSelect value={value} onChange={onChange} />
        </Provider>
    )
    await waitFor(() => expect(membersLogic.values.members).not.toBeNull())
    await waitFor(() => expect(membersLogic.values.membersLoading).toBe(false))
    return onChange
}

describe('SandboxTestRecipientSelect', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/organizations/@current/members/': {
                    results: [member('u-bo', 'Bo', true), member('u-cy', 'Cy', false), member('u-ana', 'Ana', true)],
                    next: null,
                },
            },
        })
    })

    it.each([
        ['an address outside the organization', 'person@example.com'],
        ['a member who has not verified their email', 'cy@example.com'],
    ])('replaces %s with the first verified member', async (_, value) => {
        const onChange = await renderSelect(value)

        await waitFor(() => expect(onChange).toHaveBeenCalledWith('ana@example.com'))
    })

    it('keeps a verified member', async () => {
        const onChange = await renderSelect('bo@example.com')

        expect(onChange).not.toHaveBeenCalled()
    })
})
