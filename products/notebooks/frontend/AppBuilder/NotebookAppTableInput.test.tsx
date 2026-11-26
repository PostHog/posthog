import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { NotebookAppTableInput } from './NotebookAppTableInput'

it('stages cell edits and row changes until all columns are applied together', () => {
    function Form(): JSX.Element {
        const [values, setValues] = useState<Record<string, string[]>>({ region: ['West', 'East'], owner: ['A'] })
        return (
            <>
                <NotebookAppTableInput
                    title="Routing"
                    columns={Object.entries(values).map(([name, list]) => ({ name, values: list }))}
                    disabled={false}
                    onApply={setValues}
                />
                <output>{JSON.stringify(values)}</output>
            </>
        )
    }
    render(<Form />)
    fireEvent.click(screen.getByLabelText('Remove row 1'))
    fireEvent.change(screen.getByLabelText('owner, row 1'), { target: { value: 'B' } })
    fireEvent.click(screen.getByText('Add row'))
    fireEvent.change(screen.getByLabelText('region, row 2'), { target: { value: 'North' } })
    expect(screen.getByText('{"region":["West","East"],"owner":["A"]}')).toBeTruthy()
    fireEvent.click(screen.getByText('Apply changes'))
    expect(screen.getByText('{"region":["East","North"],"owner":["B",""]}')).toBeTruthy()
})
