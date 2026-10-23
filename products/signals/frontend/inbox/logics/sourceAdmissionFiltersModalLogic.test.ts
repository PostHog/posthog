import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { admissionFormFromConfig } from '../admissionRules'
import * as inboxAnalytics from '../inboxAnalytics'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { sourceAdmissionFiltersModalLogic } from './sourceAdmissionFiltersModalLogic'

const linearConfig: SignalSourceConfig = {
    id: 'linear-1',
    source_product: SignalSourceProduct.Linear,
    source_type: SignalSourceType.Issue,
    enabled: true,
    // Keys the filters form does not own, to prove saves merge rather than clobber.
    config: {
        linear_team_ids: ['team-a'],
        steering: 'skip chores',
        admission_rules: { operator: 'AND', rules: [{ field: 'priority', operator: 'eq', value: 1 }] },
    },
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    status: null,
    admission_rule_fields: [
        { field: 'labels', kind: 'string_list' },
        { field: 'priority', kind: 'number' },
    ],
}

describe('sourceAdmissionFiltersModalLogic', () => {
    let logic: ReturnType<typeof sourceAdmissionFiltersModalLogic.build>
    let patchBodies: Record<string, any>[]
    let previewBodies: Record<string, any>[]
    let onClose: jest.Mock
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        patchBodies = []
        previewBodies = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [linearConfig], count: 1, next: null, previous: null },
                ],
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    patchBodies.push(body)
                    return [200, { ...linearConfig, ...body }]
                },
            },
            post: {
                '/api/projects/:team_id/signals/source_configs/:id/admission_preview/': async ({ request }) => {
                    previewBodies.push((await request.json()) as Record<string, any>)
                    return [
                        200,
                        {
                            issues: [],
                            truncated: false,
                            limit: 20,
                            lookback_days: 30,
                            tables_checked: 1,
                            tables_skipped: 0,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        captureSpy = jest.spyOn(inboxAnalytics, 'captureSignalSourceFiltersChanged')
        onClose = jest.fn()
        logic = sourceAdmissionFiltersModalLogic({ sourceConfig: linearConfig, onClose })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        captureSpy.mockRestore()
    })

    it('saves the rules merged into the whole config, keeps the teams picker scope, and reports the change', async () => {
        expect(logic.values.admissionFilters).toEqual({
            match: 'AND',
            rows: [{ field: 'priority', operator: 'in', values: ['1'] }],
        })

        logic.actions.setAdmissionFiltersValues({
            match: 'OR',
            rows: [
                { field: 'labels', operator: 'none', values: ['internal'] },
                { field: 'priority', operator: 'in', values: ['1', '2'] },
            ],
        })
        await expectLogic(logic, () => {
            logic.actions.submitAdmissionFilters()
        }).toDispatchActions(['submitAdmissionFiltersSuccess'])

        expect(patchBodies).toEqual([
            {
                config: {
                    linear_team_ids: ['team-a'],
                    steering: 'skip chores',
                    admission_rules: {
                        operator: 'OR',
                        rules: [
                            { field: 'labels', operator: 'none', value: ['internal'] },
                            { field: 'priority', operator: 'in', value: [1, 2] },
                        ],
                    },
                },
            },
        ])
        expect(captureSpy).toHaveBeenCalledWith({
            sourceProduct: SignalSourceProduct.Linear,
            sourceType: SignalSourceType.Issue,
            filter: 'admission_rules',
            selectedCount: 2,
            success: true,
        })
        expect(onClose).toHaveBeenCalled()
    })

    it('clears the rules by saving null', async () => {
        logic.actions.setAdmissionFiltersValues({ rows: [] })
        await expectLogic(logic, () => {
            logic.actions.submitAdmissionFilters()
        }).toDispatchActions(['submitAdmissionFiltersSuccess'])

        expect(patchBodies[0].config.admission_rules).toBeNull()
        expect(patchBodies[0].config.linear_team_ids).toEqual(['team-a'])
    })

    it('blocks a save while a filter has no values', async () => {
        logic.actions.setAdmissionFiltersValues({ rows: [{ field: 'labels', operator: 'any', values: [] }] })
        await expectLogic(logic, () => {
            logic.actions.submitAdmissionFilters()
        }).toDispatchActions(['submitAdmissionFiltersFailure'])

        expect(patchBodies).toEqual([])
    })

    it('previews the draft rules and drops the preview when the draft changes', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadPreview()
        }).toDispatchActions(['loadPreviewSuccess'])

        expect(previewBodies).toEqual([
            { admission_rules: { operator: 'AND', rules: [{ field: 'priority', operator: 'in', value: [1] }] } },
        ])
        expect(logic.values.preview).not.toBeNull()

        logic.actions.setAdmissionFiltersValue('match', 'OR')
        expect(logic.values.preview).toBeNull()
    })

    it.each([
        ['an absent tree', undefined, { match: 'AND', rows: [] }],
        ['a nested group', { operator: 'AND', rules: [{ operator: 'OR', rules: [] }] }, null],
        [
            'a neq rule',
            { operator: 'OR', rules: [{ field: 'state_name', operator: 'neq', value: 'Done' }] },
            { match: 'OR', rows: [{ field: 'state_name', operator: 'not_in', values: ['Done'] }] },
        ],
    ])('reads %s into the form', (_name, stored, expected) => {
        expect(admissionFormFromConfig({ admission_rules: stored })).toEqual(expected)
    })
})
