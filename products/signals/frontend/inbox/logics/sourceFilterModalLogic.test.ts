import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SourceFilterCatalogApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { sourceFilterModalLogic } from './sourceFilterModalLogic'

const catalog: SourceFilterCatalogApi = {
    source_product: 'linear',
    source_type: 'issue',
    catalog_version: 2,
    filter_fields: [{ name: 'assignee_id', type: 'string', description: 'Assignee.' }],
    starter_expressions: ['assignee_id IS NULL'],
}

function linearConfig(config: Record<string, any>): SignalSourceConfig {
    return {
        id: 'config-linear',
        source_product: SignalSourceProduct.Linear,
        source_type: SignalSourceType.Issue,
        enabled: true,
        // A key the filter does not own, to prove saves merge rather than clobber.
        config: { linear_team_ids: ['team-a'], ...config },
        created_at: '2026-11-01T00:00:00Z',
        updated_at: '2026-11-01T00:00:00Z',
        status: null,
    }
}

describe('sourceFilterModalLogic', () => {
    let logic: ReturnType<typeof sourceFilterModalLogic.build>
    let patchBodies: Record<string, any>[]
    let rejectWith: string | null
    let onClose: jest.Mock

    function mountWith(config: Record<string, any>): void {
        logic = sourceFilterModalLogic({ sourceConfig: linearConfig(config), catalog, onClose })
        logic.mount()
    }

    beforeEach(() => {
        patchBodies = []
        rejectWith = null
        onClose = jest.fn()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [], count: 0, next: null, previous: null },
                ],
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    if (rejectWith) {
                        return [
                            400,
                            { type: 'validation_error', code: 'invalid_input', attr: 'config', detail: rejectWith },
                        ]
                    }
                    patchBodies.push(body)
                    return [200, linearConfig({})]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    test.each([
        ['saves trimmed text', {}, '  assignee_id IS NULL  ', { config_set: { hogql_filter: 'assignee_id IS NULL' } }],
        [
            'removes the filter when the text is cleared',
            { hogql_filter: { expression: 'assignee_id IS NULL', catalog_version: 2 } },
            '   ',
            { config_remove: ['hogql_filter'] },
        ],
    ])('%s', async (_, config, expression, expectedBody) => {
        mountWith(config)
        logic.actions.setSourceFilterValue('expression', expression)

        await expectLogic(logic, () => logic.actions.submitSourceFilter()).toDispatchActions([
            'submitSourceFilterSuccess',
        ])

        expect(patchBodies).toEqual([expectedBody])
        expect(onClose).toHaveBeenCalled()
    })

    it('shows a rejected expression under the field until it is edited', async () => {
        rejectWith = 'hogql_filter: Use an unqualified field from the filter catalog.'
        mountWith({})
        logic.actions.setSourceFilterValue('expression', "projct = 'Core'")

        await expectLogic(logic, () => logic.actions.submitSourceFilter()).toDispatchActions([
            'submitSourceFilterFailure',
        ])

        expect(logic.values.sourceFilterAllErrors).toEqual({
            expression: 'Use an unqualified field from the filter catalog.',
        })
        expect(onClose).not.toHaveBeenCalled()

        logic.actions.setSourceFilterValue('expression', "project_name = 'Core'")
        expect(logic.values.sourceFilterAllErrors).toEqual({})
    })
})
