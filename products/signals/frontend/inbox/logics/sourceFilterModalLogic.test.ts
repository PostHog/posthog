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
    preview_supported: true,
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
    let createBodies: unknown[]
    let patchBodies: Record<string, any>[]
    let rejectWith: string | null
    let integrationsFail: boolean
    let onClose: jest.Mock

    function mountWith(config: Record<string, any>): void {
        logic = sourceFilterModalLogic({ sourceConfig: linearConfig(config), catalog, onClose })
        logic.mount()
    }

    beforeEach(() => {
        createBodies = []
        patchBodies = []
        rejectWith = null
        integrationsFail = false
        onClose = jest.fn()
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () =>
                    integrationsFail ? [500, { detail: 'Internal server error' }] : [200, { results: [] }],
                '/api/environments/:team_id/integrations/': () =>
                    integrationsFail ? [500, { detail: 'Internal server error' }] : [200, { results: [] }],
                '/api/environments/:team_id/external_data_sources/': () => [200, { results: [] }],
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [], count: 0, next: null, previous: null },
                ],
            },
            post: {
                '/api/projects/:team_id/signals/source_configs/': async ({ request }) => {
                    createBodies.push(await request.json())
                    return [201, linearConfig({ linear_team_ids: [] })]
                },
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
        [
            'saves trimmed text and leaves unchanged teams alone',
            {},
            { expression: '  assignee_id IS NULL  ' },
            { config_set: { hogql_filter: 'assignee_id IS NULL' } },
        ],
        [
            'removes the filter when the text is cleared',
            { hogql_filter: { expression: 'assignee_id IS NULL', catalog_version: 2 } },
            { expression: '   ' },
            { config_remove: ['hogql_filter'] },
        ],
        [
            'leaves an unchanged filter on its catalog version when only teams change',
            { hogql_filter: { expression: "project_name = 'Mobile'", catalog_version: 1 } },
            { teamIds: ['team-b'] },
            { config_set: { linear_team_ids: ['team-b'] } },
        ],
        [
            'clears the last team while keeping the saved expression',
            { hogql_filter: { expression: 'assignee_id IS NULL', catalog_version: 2 } },
            { teamIds: [] },
            { config_set: { linear_team_ids: [] } },
        ],
        [
            'saves teams and the filter in one request',
            {},
            { expression: 'assignee_id IS NULL', teamIds: ['team-b'] },
            { config_set: { hogql_filter: 'assignee_id IS NULL', linear_team_ids: ['team-b'] } },
        ],
    ])('%s', async (_, config, values, expectedBody) => {
        mountWith(config)
        logic.actions.setSourceFilterValues(values)

        await expectLogic(logic, () => logic.actions.submitSourceFilter()).toDispatchActions([
            'submitSourceFilterSuccess',
        ])

        expect(patchBodies).toEqual([expectedBody])
        expect(onClose).toHaveBeenCalled()
    })

    it('turns on a new Linear source with an expression and no teams', async () => {
        logic = sourceFilterModalLogic({
            sourceConfig: { ...linearConfig({}), id: 'new_linear_issue', enabled: false, config: {} },
            catalog,
            enableOnSave: { viaSetupWizard: true },
            onClose,
        })
        logic.mount()
        logic.actions.setSourceFilterValue('expression', 'assignee_id IS NULL')

        await expectLogic(logic, () => logic.actions.submitSourceFilter()).toDispatchActions([
            'submitSourceFilterSuccess',
        ])

        expect(createBodies).toEqual([
            {
                source_product: 'linear',
                source_type: 'issue',
                enabled: true,
                config: { hogql_filter: 'assignee_id IS NULL' },
            },
        ])
    })

    it('refuses to save after the last Linear team is removed', async () => {
        mountWith({})
        logic.actions.setSourceFilterValue('teamIds', [])

        await expectLogic(logic, () => logic.actions.submitSourceFilter()).toDispatchActions([
            'submitSourceFilterFailure',
        ])

        expect(patchBodies).toEqual([])
        expect(onClose).not.toHaveBeenCalled()
    })

    it('keeps the last expression when it is the only filter on an enabled source', async () => {
        mountWith({ linear_team_ids: [], hogql_filter: { expression: 'assignee_id IS NULL', catalog_version: 2 } })
        logic.actions.setSourceFilterValue('expression', '  ')

        await expectLogic(logic, () => logic.actions.submitSourceFilter()).toDispatchActions([
            'submitSourceFilterFailure',
        ])
        await expectLogic(logic, () => logic.actions.removeFilter()).toDispatchActions(['removeFilterFinished'])

        expect(patchBodies).toEqual([])
    })

    it('shows a rejected expression under the field until it is edited', async () => {
        rejectWith = 'hogql_filter: Use an unqualified field from the filter catalog.'
        mountWith({})
        logic.actions.setSourceFilterValue('expression', "projct = 'Core'")

        await expectLogic(logic, () => logic.actions.submitSourceFilter()).toDispatchActions([
            'submitSourceFilterFailure',
        ])

        expect(logic.values.sourceFilterAllErrors.expression).toBe('Use an unqualified field from the filter catalog.')
        expect(onClose).not.toHaveBeenCalled()

        logic.actions.setSourceFilterValue('expression', "project_name = 'Core'")
        expect(logic.values.sourceFilterHasErrors).toBe(false)
    })

    it('reports a failed Linear connection load and recovers on retry', async () => {
        integrationsFail = true
        mountWith({})
        await expectLogic(logic).toDispatchActions(['loadIntegrationsFailure'])
        expect(logic.values.integrationsLoadFailed).toBe(true)

        integrationsFail = false
        await expectLogic(logic, () => logic.actions.loadIntegrations()).toDispatchActions(['loadIntegrationsSuccess'])
        expect(logic.values.integrationsLoadFailed).toBe(false)
    })
})
