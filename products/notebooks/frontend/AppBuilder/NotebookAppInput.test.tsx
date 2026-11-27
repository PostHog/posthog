import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import type { NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import { NotebookAppQueryChoicesContext } from './notebookAppChoices'
import { NotebookAppInput } from './NotebookAppInput'

it('adds a whole dropdown option to a list and clears the selection', async () => {
    function RegionsFilter(): JSX.Element {
        const [value, setValue] = useState<NotebookVariableValue>(['North'])
        return (
            <NotebookAppInput
                block={{
                    id: 'regions',
                    tab_id: 'overview',
                    kind: 'input',
                    input_kind: 'select',
                    options: ['North', 'East, West'],
                }}
                variable={{ name: 'regions', type: 'list', value }}
                disabled={false}
                onChange={setValue}
            />
        )
    }
    const { container } = render(<RegionsFilter />)
    const selected = within(container)
    await userEvent.click(screen.getByLabelText('regions'))
    await userEvent.click(await screen.findByText('East, West'))
    expect(selected.getByText('North')).toBeTruthy()
    expect(selected.getByText('East, West')).toBeTruthy()
    await userEvent.click(await screen.findByText('Clear all'))
    expect(selected.queryByText('North')).toBeNull()
    expect(selected.queryByText('East, West')).toBeNull()
})

it('explains how to recover unavailable published query options', () => {
    render(
        <NotebookAppQueryChoicesContext.Provider value={() => 'unavailable'}>
            <NotebookAppInput
                block={{ id: 'regions', tab_id: 'overview', kind: 'input', input_kind: 'query_select' }}
                variable={{ name: 'region', type: 'string', value: '' }}
                disabled={false}
                onChange={jest.fn()}
            />
        </NotebookAppQueryChoicesContext.Provider>
    )
    expect(screen.getByRole('status').textContent).toContain('Refresh results')
})

it.each(['string', 'list'] as const)(
    'excludes query values from autocapture in the %s control and its portal',
    async (type) => {
        const { container, unmount } = render(
            <NotebookAppQueryChoicesContext.Provider value={() => ({ values: ['Alpha', 'Bravo'], partial: false })}>
                <NotebookAppInput
                    block={{ id: 'region', tab_id: 'overview', kind: 'input', input_kind: 'query_select' }}
                    variable={{ name: 'region', type, value: type === 'list' ? ['Alpha'] : 'Alpha' }}
                    disabled={false}
                    onChange={jest.fn()}
                />
            </NotebookAppQueryChoicesContext.Provider>
        )
        const control = within(container)
        const selected = control.getByText('Alpha')
        expect(selected.closest('.ph-no-capture')).toBeTruthy()
        await userEvent.click(control.getByLabelText('region'))
        const option = await screen.findByText('Bravo')
        expect(option.closest('.ph-no-capture')).toBeTruthy()
        unmount()
    }
)
