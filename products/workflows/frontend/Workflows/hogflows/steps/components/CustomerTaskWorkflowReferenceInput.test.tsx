import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER, MOCK_USER_UUID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CustomerTaskWorkflowReferenceInput } from './CustomerTaskWorkflowReferenceInput'

jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
        <input aria-label="Raw expression" value={value} onChange={(event) => onChange(event.target.value)} />
    ),
}))

const accountId = '11111111-1111-4111-8111-111111111111'

describe('CustomerTaskWorkflowReferenceInput', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:project_id/accounts/': { results: [{ id: accountId, name: 'Example account' }] },
                '/api/organizations/:organization_id/members/': {
                    results: [
                        { id: '1', user: MOCK_DEFAULT_BASIC_USER, level: 8 },
                        { id: '2', user: MOCK_SECOND_BASIC_USER, level: 1 },
                    ],
                },
            },
        })
        initKeaTests()
        userLogic().mount()
        await expectLogic(userLogic).toMatchValues({ user: expect.objectContaining({ uuid: MOCK_USER_UUID }) })
    })
    afterEach(cleanup)

    function renderInput(key: string, value: string, onChange = jest.fn()): jest.Mock {
        render(
            <Provider>
                <CustomerTaskWorkflowReferenceInput
                    schema={{ key, type: 'string', label: key }}
                    input={{ value, templating: 'hog' }}
                    onChange={onChange}
                    projectId={1}
                    sampleGlobals={{}}
                />
            </Provider>
        )
        return onChange
    }

    it.each(['account_id', 'assigned_to_id'])(
        'preserves %s expressions across mode changes and raw edits',
        async (key) => {
            const expression = '{variables.account_or_user}'
            const onChange = renderInput(key, expression)
            fireEvent.click(screen.getByText('Picker'))
            expect(onChange).not.toHaveBeenCalled()
            expect(screen.getByText('Choose a value to replace the raw expression.')).toBeInTheDocument()
            fireEvent.click(screen.getByText('Raw'))
            expect(screen.getByLabelText('Raw expression')).toHaveValue(expression)
            fireEvent.change(screen.getByLabelText('Raw expression'), { target: { value: '{variables.other}' } })
            expect(onChange).toHaveBeenCalledWith({ value: '{variables.other}', templating: 'hog' })
        }
    )

    it('stores the picked account UUID and preserves templating metadata', async () => {
        const onChange = renderInput('account_id', '')
        fireEvent.click(screen.getByText('Picker'))
        fireEvent.click(screen.getByPlaceholderText('No account'))
        await waitFor(() => expect(screen.getByText('Example account')).toBeInTheDocument())
        fireEvent.click(screen.getByText('Example account'))
        expect(onChange).toHaveBeenCalledWith({ value: accountId, templating: 'hog' })
    })

    it('resolves a saved member on entering Picker without opening the member menu', async () => {
        const onChange = renderInput('assigned_to_id', String(MOCK_SECOND_BASIC_USER.id))
        fireEvent.click(screen.getByText('Picker'))
        await waitFor(() => expect(screen.getByText(MOCK_SECOND_BASIC_USER.first_name)).toBeInTheDocument())
        expect(onChange).not.toHaveBeenCalled()
    })

    it('stores the picked member as a string ID for the templated schema', async () => {
        const onChange = renderInput('assigned_to_id', '{variables.owner_id}')
        fireEvent.click(screen.getByText('Picker'))
        fireEvent.click(screen.getByText('Unassigned'))
        await waitFor(() => expect(screen.getByText(MOCK_SECOND_BASIC_USER.first_name)).toBeInTheDocument())
        fireEvent.click(screen.getByText(MOCK_SECOND_BASIC_USER.first_name))
        expect(onChange).toHaveBeenCalledWith({ value: String(MOCK_SECOND_BASIC_USER.id), templating: 'hog' })
    })
})
