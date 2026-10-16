import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { useState } from 'react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInputSchemaType } from '~/types'

import CyclotronJobInputTaskRepository from './CyclotronJobInputTaskRepository'

jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
        <input aria-label="Repository template" value={value} onChange={(event) => onChange(event.target.value)} />
    ),
}))

const SCHEMA: CyclotronJobInputSchemaType = { key: 'repository', type: 'task_repository', label: 'Repository' }
const TEMPLATED = { template: '{event.properties.repository}', allowed: ['example-org/api'] }

function ControlledRepositoryInput({ initial, onChange }: { initial: unknown; onChange: jest.Mock }): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
        <CyclotronJobInputTaskRepository
            value={value}
            onChange={(next) => {
                onChange(next)
                setValue(next)
            }}
            schema={SCHEMA}
        />
    )
}

describe('CyclotronJobInputTaskRepository', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/integrations': { results: [] } } })
        initKeaTests()
    })
    afterEach(cleanup)

    const switchTo = (mode: 'Pick' | 'Template'): void => {
        fireEvent.click(document.querySelector('[data-attr="task-repository-input-mode"]')!)
        fireEvent.click(screen.getByRole('menuitem', { name: mode }))
    }

    it('keeps each mode value when the author switches back and forth', () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <ControlledRepositoryInput initial={TEMPLATED} onChange={onChange} />
            </Provider>
        )

        switchTo('Pick')
        expect(onChange).toHaveBeenLastCalledWith(null)
        expect(screen.queryByLabelText('Repository template')).not.toBeInTheDocument()

        switchTo('Template')
        expect(onChange).toHaveBeenLastCalledWith(TEMPLATED)
        expect(screen.getByLabelText('Repository template')).toHaveValue(TEMPLATED.template)
    })

    it.each([
        ['a template replaced by a picked repository', TEMPLATED, 'example-org/api', false],
        ['a picked repository replaced by a template', 'example-org/api', TEMPLATED, true],
    ])('shows the mode of %s from outside the editor', (_case, before, after, showsTemplate) => {
        const { rerender } = render(
            <Provider>
                <CyclotronJobInputTaskRepository value={before} onChange={jest.fn()} schema={SCHEMA} />
            </Provider>
        )

        rerender(
            <Provider>
                <CyclotronJobInputTaskRepository value={after} onChange={jest.fn()} schema={SCHEMA} />
            </Provider>
        )

        expect(!!screen.queryByLabelText('Repository template')).toBe(showsTemplate)
    })
})
