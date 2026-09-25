import { findFacet } from 'lib/components/FacetSearchBar/facetQuery'

import { buildWorkflowListFacets } from './workflowListFacets'
import { WorkflowListRow, buildWorkflowListRows } from './workflowListRows'
import { FIXTURE_USERS, buildTemplateRow, buildWorkflowRow, emailStep } from './workflowsListV2Fixtures'

const valuesOf = (facetKey: string, row: WorkflowListRow): string[] =>
    findFacet(buildWorkflowListFacets([]), facetKey)!.getValues(row)

describe('buildWorkflowListRows', () => {
    it.each([
        [
            'an explicit owner wins over the creator',
            'Owner: @Maya. Sends the welcome mail.',
            FIXTURE_USERS.ada,
            ['maya'],
        ],
        [
            'every explicit owner counts, trailing dots and dashes trimmed',
            'owner: @sam-  OWNER: @li.wei.',
            null,
            ['sam', 'li.wei'],
        ],
        ['any other mention does not count', 'Ask @maya first', FIXTURE_USERS.ada, ['ada']],
        ['the creator without a first name gives their email name', '', FIXTURE_USERS.lin, ['lin.ops']],
        ['no owner and no creator gives nothing', '', null, []],
    ])('owner: %s', (_, description, createdBy, expected) => {
        const [row] = buildWorkflowListRows([buildWorkflowRow({ id: 'wf', description, created_by: createdBy })], [])
        expect(valuesOf('owner', row)).toEqual(expected)
    })

    it.each([
        [{ succeeded: 10, failed: 1 }, 'failing'],
        [{ succeeded: 10, failed: 0 }, 'healthy'],
        [{ succeeded: 0, failed: 0 }, 'idle'],
        [null, 'idle'],
    ])('health for %j is %s', (last7Days, expected) => {
        const [row] = buildWorkflowListRows([buildWorkflowRow({ id: 'wf', last_7_days: last7Days })], [])
        expect(valuesOf('health', row)).toEqual([expected])
    })

    it('merges workflows and email templates, newest first, with template channel, sends and from', () => {
        const rows = buildWorkflowListRows(
            [
                buildWorkflowRow({
                    id: 'wf-old',
                    updated_at: '2026-09-01T00:00:00Z',
                    channels: ['email', 'sms'],
                    email_steps: [
                        emailStep('e1', 'First subject', ['one@example.com']),
                        emailStep('e2', '', ['two@example.com', 'one@example.com']),
                    ],
                }),
                buildWorkflowRow({ id: 'wf-new', updated_at: '2026-09-03T00:00:00Z' }),
            ],
            [
                buildTemplateRow({
                    id: 'tpl',
                    subject: 'Receipt',
                    from_addresses: ['billing@example.com'],
                    updated_at: '2026-09-02T00:00:00Z',
                }),
            ]
        )

        expect(rows.map((row) => [row.kind, row.id])).toEqual([
            ['workflow', 'wf-new'],
            ['email_template', 'tpl'],
            ['workflow', 'wf-old'],
        ])
        const [, template, workflow] = rows
        expect(valuesOf('kind', template)).toEqual(['email-template'])
        expect(valuesOf('channel', template)).toEqual(['email'])
        expect(valuesOf('sends', template)).toEqual(['Receipt'])
        expect(valuesOf('from', template)).toEqual(['billing@example.com'])
        expect(valuesOf('status', template)).toEqual([])
        expect(valuesOf('owner', template)).toEqual([])
        expect(valuesOf('created-by', template)).toEqual([FIXTURE_USERS.lin.uuid])

        expect(valuesOf('kind', workflow)).toEqual(['workflow'])
        expect(valuesOf('channel', workflow)).toEqual(['email', 'sms'])
        expect(valuesOf('sends', workflow)).toEqual(['First subject'])
        expect(valuesOf('from', workflow)).toEqual(['one@example.com', 'two@example.com'])
    })
})
