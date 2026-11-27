import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import type { NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import { NotebookAppDateRange } from './NotebookAppDateRange'
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

it('shows saved ISO dates and keeps open bounds unrestricted', () => {
    const block = { id: 'range', tab_id: 'overview', kind: 'input' as const, variable: 'start', end_variable: 'end' }
    const renderRange = (end: string | null): JSX.Element => (
        <NotebookAppDateRange
            block={block}
            variables={[
                { name: 'start', type: 'date', value: '2026-W01-1' },
                { name: 'end', type: 'date', value: end },
            ]}
            disabled={false}
            onChange={jest.fn()}
        />
    )
    const { rerender } = render(renderRange('20260930T23:00:00-06:00'))
    const start = screen.getByLabelText<HTMLInputElement>('From')
    const end = screen.getByLabelText<HTMLInputElement>('Through')
    expect([start.value, end.min]).toEqual(['2025-12-29', '2025-12-29'])
    expect([end.value, start.max]).toEqual(['2026-09-30', '2026-09-30'])
    rerender(renderRange(null))
    expect([end.value, start.max]).toEqual(['', ''])
})
