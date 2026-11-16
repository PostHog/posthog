import type { UserBasicApi, WorkflowStatsRowApi } from 'products/workflows/frontend/generated/api.schemas'

import { buildWorkflowListRows } from './workflowListRows'
import { FIXTURE_USERS, buildWorkflowRow } from './workflowsListV2Fixtures'

describe('buildWorkflowListRows', () => {
    it.each<[string, string, UserBasicApi | null, string[]]>([
        [
            'an explicit owner wins over the creator',
            'Owner: @Maya. Sends the welcome mail.',
            FIXTURE_USERS.ada,
            ['maya'],
        ],
        [
            'every explicit owner counts, trailing dots and dashes trimmed',
            'owner: @sam-; OWNER: @li.wei.',
            null,
            ['sam', 'li.wei'],
        ],
        ['a repeated owner counts once', 'Owner: @kim. Owner: @Kim', null, ['kim']],
        ['any other mention does not count', 'Ask @maya first', FIXTURE_USERS.ada, ['ada']],
        ['a co-owner is not the owner', 'Co-owner: @sam', FIXTURE_USERS.ada, ['ada']],
        ['a previous owner is not the owner', 'Previous owner: @jo', FIXTURE_USERS.ada, ['ada']],
        ['a bullet line counts', 'Sends reminders.\n- Owner: @kim', FIXTURE_USERS.lin, ['kim']],
        ['an owner in parentheses counts', 'Weekly digest (owner: @kim)', FIXTURE_USERS.ada, ['kim']],
        ['the creator gives their first name', '', FIXTURE_USERS.ada, ['ada']],
        ['the creator without a first name gives their email name', '', FIXTURE_USERS.lin, ['lin.ops']],
        ['no owner and no creator gives nothing', '', null, []],
    ])('owners: %s', (_, description, createdBy, owners) => {
        const [row] = buildWorkflowListRows(
            [buildWorkflowRow({ id: 'wf', description, created_by: createdBy as UserBasicApi })],
            null
        )

        expect(row.owners).toEqual(owners)
    })

    it.each<[string, WorkflowStatsRowApi[] | null, object]>([
        ['metrics still loading', null, { last7Days: null, health: 'idle' }],
        ['no metrics row for the workflow', [], { last7Days: { succeeded: 0, failed: 0 }, health: 'idle' }],
        ['a row with no runs', [{ workflow_id: 'wf', succeeded: 0, failed: 0 }], { health: 'idle' }],
        [
            'only another workflow ran',
            [{ workflow_id: 'wf-other', succeeded: 4, failed: 2 }],
            { last7Days: { succeeded: 0, failed: 0 }, health: 'idle' },
        ],
        [
            'a failed run among successes',
            [{ workflow_id: 'wf', succeeded: 10, failed: 1 }],
            { last7Days: { succeeded: 10, failed: 1 }, health: 'failing' },
        ],
        ['only succeeded runs', [{ workflow_id: 'wf', succeeded: 10, failed: 0 }], { health: 'healthy' }],
    ])('metrics and health with %s', (_, metrics, expected) => {
        const [row] = buildWorkflowListRows([buildWorkflowRow({ id: 'wf' })], metrics)

        expect(row).toMatchObject(expected)
    })

    it('puts the most recently updated workflow first', () => {
        const rows = buildWorkflowListRows(
            [
                buildWorkflowRow({
                    id: 'wf-older',
                    name: 'A',
                    created_at: '2026-09-01T00:00:00Z',
                    updated_at: '2026-09-02T00:00:00Z',
                }),
                buildWorkflowRow({
                    id: 'wf-newest',
                    name: 'C',
                    created_at: '2026-07-01T00:00:00Z',
                    updated_at: '2026-09-20T08:00:00Z',
                }),
                buildWorkflowRow({
                    id: 'wf-middle',
                    name: 'B',
                    created_at: '2026-08-01T00:00:00Z',
                    updated_at: '2026-09-20T07:59:00Z',
                }),
            ],
            null
        )

        expect(rows.map((row) => row.id)).toEqual(['wf-newest', 'wf-middle', 'wf-older'])
    })
})
