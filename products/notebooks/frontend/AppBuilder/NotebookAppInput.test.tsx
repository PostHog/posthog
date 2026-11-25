import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { NotebookAppInput } from './NotebookAppInput'

it('adds a whole dropdown option to a list and clears the selection', async () => {
    const onChange = jest.fn()
    render(
        <NotebookAppInput
            block={{
                id: 'regions',
                tab_id: 'overview',
                kind: 'input',
                input_kind: 'select',
                options: ['North', 'East, West'],
            }}
            variable={{ name: 'regions', type: 'list', value: ['North'] }}
            disabled={false}
            onChange={onChange}
        />
    )
    await userEvent.click(screen.getByLabelText('regions'))
    await userEvent.click(await screen.findByText('East, West'))
    expect(onChange).toHaveBeenCalledWith(['North', 'East, West'])
    await userEvent.click(await screen.findByText('Clear all'))
    expect(onChange).toHaveBeenLastCalledWith([])
})
