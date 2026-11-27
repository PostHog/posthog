import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import type { NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import { initKeaTests } from '~/test/init'

import { NotebookAppCanvas } from './NotebookAppCanvas'
import { emptyAppLayout } from './notebookAppLayout'

it('stages cell edits and row changes until all columns are applied together', () => {
    function Form(): JSX.Element {
        const [visible, setVisible] = useState(true)
        const [values, setValues] = useState<Record<string, NotebookVariableValue>>({
            region: ['West', 'East'],
            owner: ['A'],
        })
        return (
            <>
                <button onClick={() => setVisible(!visible)}>Switch tab</button>
                <NotebookAppCanvas
                    layout={{
                        ...emptyAppLayout(),
                        blocks: [
                            {
                                id: 'routing',
                                tab_id: 'table',
                                kind: 'input',
                                input_kind: 'table',
                                variable: 'region',
                                table_columns: ['owner'],
                            },
                        ],
                    }}
                    activeTab={visible ? 'table' : 'other'}
                    cells={[]}
                    staleNodeIds={{}}
                    variables={Object.entries(values).map(([name, value]) => ({ name, type: 'list', value }))}
                    canInteract
                    editing={false}
                    selectedId={null}
                    onInput={setValues}
                />
                <output>{JSON.stringify(values)}</output>
            </>
        )
    }
    initKeaTests()
    render(<Form />)
    fireEvent.click(screen.getByLabelText('Remove row 1'))
    fireEvent.change(screen.getByLabelText('owner, row 1'), { target: { value: 'B' } })
    fireEvent.click(screen.getByText('Add row'))
    fireEvent.change(screen.getByLabelText('region, row 2'), { target: { value: 'North' } })
    fireEvent.click(screen.getByText('Switch tab'))
    fireEvent.click(screen.getByText('Switch tab'))
    expect(screen.getByText('{"region":["West","East"],"owner":["A"]}')).toBeTruthy()
    fireEvent.click(screen.getByText('Apply changes'))
    expect(screen.getByText('{"region":["East","North"],"owner":["B",""]}')).toBeTruthy()
})
