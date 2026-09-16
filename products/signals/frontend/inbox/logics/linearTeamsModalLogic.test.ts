import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signalSourcesLogic } from '../signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { linearTeamsModalLogic } from './linearTeamsModalLogic'

const existingConfig: SignalSourceConfig = {
    id: 'config-linear',
    source_product: SignalSourceProduct.Linear,
    source_type: SignalSourceType.Issue,
    enabled: false,
    // A key the picker does not own, to prove saves merge rather than clobber.
    config: { steering: 'Skip chores', linear_team_ids: ['team-1'] },
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    status: null,
}

describe('linearTeamsModalLogic', () => {
    let requests: { method: string; body: Record<string, any> }[]
    let onClose: jest.Mock

    beforeEach(() => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [existingConfig], count: 1, next: null, previous: null },
                ],
            },
            post: {
                '/api/projects/:team_id/signals/source_configs/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    requests.push({ method: 'POST', body })
                    return [201, { ...existingConfig, id: 'config-new', ...body }]
                },
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    requests.push({ method: 'PATCH', body })
                    return [200, { ...existingConfig, ...body }]
                },
            },
        })
        initKeaTests()
        onClose = jest.fn()
    })

    it.each([
        {
            name: 'a pick from Filters keeps the other keys and leaves enabled alone',
            props: { config: existingConfig, enableOnSave: false },
            form: { scope: 'selected' as const, teamIds: ['team-1', 'team-2'] },
            expected: {
                method: 'PATCH',
                body: { enabled: false, config: { steering: 'Skip chores', linear_team_ids: ['team-1', 'team-2'] } },
            },
        },
        {
            name: 'reading all teams writes an empty list',
            props: { config: existingConfig, enableOnSave: false },
            form: { scope: 'all' as const, teamIds: ['team-1'] },
            expected: {
                method: 'PATCH',
                body: { enabled: false, config: { steering: 'Skip chores', linear_team_ids: [] } },
            },
        },
        {
            name: 'the enable flow turns the source on with the pick',
            props: { config: existingConfig, enableOnSave: true },
            form: { scope: 'selected' as const, teamIds: ['team-2'] },
            expected: {
                method: 'PATCH',
                body: { enabled: true, config: { steering: 'Skip chores', linear_team_ids: ['team-2'] } },
            },
        },
    ])('$name', async ({ props, form, expected }) => {
        const sourcesLogic = signalSourcesLogic()
        sourcesLogic.mount()
        await expectLogic(sourcesLogic, () => sourcesLogic.actions.loadSourceConfigs()).toDispatchActions([
            'loadSourceConfigsSuccess',
        ])
        const logic = linearTeamsModalLogic({ ...props, viaSetupWizard: false, onClose })
        logic.mount()

        logic.actions.setLinearTeamsValues(form)
        await expectLogic(logic, () => logic.actions.submitLinearTeams()).toDispatchActions([
            'submitLinearTeamsSuccess',
            'toggleSignalSourceSuccess',
        ])

        expect(requests).toEqual([expected])
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('creates the row when Linear was never turned on before', async () => {
        const logic = linearTeamsModalLogic({ config: null, enableOnSave: true, viaSetupWizard: true, onClose })
        logic.mount()
        expect(logic.values.linearTeams).toEqual({ scope: 'all', teamIds: [] })

        await expectLogic(logic, () => logic.actions.submitLinearTeams()).toDispatchActions([
            'toggleSignalSourceSuccess',
        ])

        expect(requests).toEqual([
            {
                method: 'POST',
                body: {
                    source_product: 'linear',
                    source_type: 'issue',
                    enabled: true,
                    config: { linear_team_ids: [] },
                },
            },
        ])
    })

    it('refuses to save a pick with no teams', async () => {
        const logic = linearTeamsModalLogic({
            config: existingConfig,
            enableOnSave: false,
            viaSetupWizard: false,
            onClose,
        })
        logic.mount()

        logic.actions.setLinearTeamsValues({ scope: 'selected', teamIds: [] })
        await expectLogic(logic, () => logic.actions.submitLinearTeams()).toDispatchActions([
            'submitLinearTeamsFailure',
        ])

        expect(logic.values.linearTeamsValidationErrors.scope).toBe('Pick at least one team, or read all teams.')
        expect(requests).toEqual([])
        expect(onClose).not.toHaveBeenCalled()
    })
})
