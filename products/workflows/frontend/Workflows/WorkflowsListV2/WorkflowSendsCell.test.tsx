import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import type { FacetFilter } from 'lib/components/FacetSearchBar/facetQuery'

import { buildWorkflowListRows } from './workflowListRows'
import { WorkflowSendsCell } from './WorkflowSendsCell'
import { buildTemplateRow, buildWorkflowRow, emailStep } from './workflowsListV2Fixtures'

const [workflowRow, templateRow] = buildWorkflowListRows(
    [
        buildWorkflowRow({
            id: 'wf',
            updated_at: '2026-09-02T00:00:00Z',
            channels: ['email'],
            dispatches: [{ action_type: 'function_email', template_id: 'template-email', count: 3 }],
            email_steps: [
                emailStep('e1', 'Welcome aboard', ['hello@example.com']),
                emailStep('e2', 'Your trial ends', ['billing@example.com']),
                emailStep('e3', 'Last chance', ['billing@example.com']),
            ],
        }),
    ],
    [
        buildTemplateRow({
            id: 'tpl',
            subject: 'Your receipt',
            from_addresses: ['receipts@example.com'],
            updated_at: '2026-09-01T00:00:00Z',
        }),
    ]
)

const renderCell = (row: typeof workflowRow, filters: FacetFilter[] = []): HTMLElement =>
    render(<WorkflowSendsCell row={row} filters={filters} />).container

describe('WorkflowSendsCell', () => {
    afterEach(() => cleanup())

    it.each<[string, FacetFilter[], string, string | null, string | null]>([
        ['shows the first email step without pills', [], 'Welcome aboard', null, null],
        [
            'highlights the step a sends: pill matches',
            [{ facet: 'sends', value: 'your trial ends', negated: false }],
            'Your trial ends',
            'Your trial ends',
            null,
        ],
        [
            'highlights the first step a from: pill matches and counts the others',
            [{ facet: 'from', value: 'billing@example.com', negated: false }],
            'Your trial ends',
            'billing@example.com',
            '+1',
        ],
        [
            'ignores a negated pill',
            [{ facet: 'from', value: 'hello@example.com', negated: true }],
            'Welcome aboard',
            null,
            null,
        ],
    ])('%s', (_, filters, subject, marked, more) => {
        const cell = renderCell(workflowRow, filters)
        expect(cell.querySelector('[data-attr="workflow-sends-subject"]')).toHaveTextContent(subject)
        expect(cell.querySelector('mark')?.textContent ?? null).toEqual(marked)
        expect(cell.querySelector('[data-attr="workflow-sends-more"]')?.textContent ?? null).toEqual(more)
    })

    it('shows an email template subject and From address', () => {
        const cell = renderCell(templateRow)
        expect(cell.querySelector('[data-attr="workflow-sends-subject"]')).toHaveTextContent('Your receipt')
        expect(cell).toHaveTextContent('receipts@example.com')
    })
})
