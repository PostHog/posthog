import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import type { NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

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
