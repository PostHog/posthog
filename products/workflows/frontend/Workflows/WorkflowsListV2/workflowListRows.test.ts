import type { UserBasicApi } from 'products/workflows/frontend/generated/api.schemas'

import { findFacet } from './FacetSearchBar/facetQuery'
import { buildWorkflowListFacets } from './workflowListFacets'
import { WorkflowListRow, buildWorkflowListRows } from './workflowListRows'
import { FIXTURE_USERS, buildWorkflowRow } from './workflowsListV2Fixtures'

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
            'owner: @sam-; OWNER: @li.wei.',
            null,
            ['sam', 'li.wei'],
        ],
        ['any other mention does not count', 'Ask @maya first', FIXTURE_USERS.ada, ['ada']],
        ['a co-owner is not the owner', 'Co-owner: @sam', FIXTURE_USERS.ada, ['ada']],
        ['a dash bullet counts', 'Sends reminders.\n- Owner: @kim', FIXTURE_USERS.lin, ['kim']],
        ['a star bullet counts', '* Owner: @kim', FIXTURE_USERS.lin, ['kim']],
        ['an indented line counts', 'Sends reminders\n  Owner: @kim', FIXTURE_USERS.lin, ['kim']],
        ['a previous owner is not the owner', 'Previous owner: @jo', FIXTURE_USERS.ada, ['ada']],
        ['an owner in parentheses counts', 'Weekly digest (owner: @kim)', FIXTURE_USERS.ada, ['kim']],
        ['the creator without a first name gives their email name', '', FIXTURE_USERS.lin, ['lin.ops']],
        ['no owner and no creator gives nothing', '', null, []],
    ])('owner: %s', (_, description, createdBy, expected) => {
        const [row] = buildWorkflowListRows(
            [buildWorkflowRow({ id: 'wf', description, created_by: createdBy as UserBasicApi })],
            null
        )
        expect(valuesOf('owner', row)).toEqual(expected)
    })

    it.each([
        ['a failed run', [{ workflow_id: 'wf', succeeded: 10, failed: 1 }], 'failing'],
        ['only succeeded runs', [{ workflow_id: 'wf', succeeded: 10, failed: 0 }], 'healthy'],
        ['a row with no runs', [{ workflow_id: 'wf', succeeded: 0, failed: 0 }], 'idle'],
        ['no row for the workflow', [], 'idle'],
        ['metrics not loaded', null, 'idle'],
    ])('health with %s', (_, metrics, expected) => {
        const [row] = buildWorkflowListRows([buildWorkflowRow({ id: 'wf' })], metrics)
        expect(valuesOf('health', row)).toEqual([expected])
    })

    it.each([
        ['an event trigger', { type: 'event' }, ['event']],
        ['no trigger', null, []],
        ['a trigger without a type', {}, []],
    ])('trigger from %s', (_, trigger, expected) => {
        const [row] = buildWorkflowListRows([buildWorkflowRow({ id: 'wf', trigger })], null)
        expect(valuesOf('trigger', row)).toEqual(expected)
    })
})
