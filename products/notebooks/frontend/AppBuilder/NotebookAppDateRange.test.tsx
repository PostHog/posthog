import { render, screen } from '@testing-library/react'

import { NotebookAppDateRange } from './NotebookAppDateRange'

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
