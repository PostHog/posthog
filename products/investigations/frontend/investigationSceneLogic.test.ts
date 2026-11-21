import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { newInvestigation } from './investigationDocument'
import { investigationSceneLogic } from './investigationSceneLogic'

const record = {
    id: '019a0000-0000-7000-8000-000000000001',
    document: newInvestigation('What changed?'),
    question: 'What changed?',
    status: 'investigating',
    revision: 1,
    evidence_count: 0,
    run_count: 0,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    created_by: 1,
}

describe('investigation persistence', () => {
    let logic: ReturnType<typeof investigationSceneLogic.build>
    beforeEach(async () => {
        initKeaTests()
        useMocks({ get: { '/api/projects/:team_id/investigations/:id/': record } })
        logic = investigationSceneLogic({ id: record.id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })
    afterEach(() => logic.unmount())

    it('keeps edits made during a save dirty until they are saved too', async () => {
        let finish: () => void = () => {}
        const pending = new Promise<void>((resolve) => {
            finish = resolve
        })
        useMocks({
            patch: {
                '/api/projects/:team_id/investigations/:id/': async ({ request }) => {
                    const body = (await request.json()) as { document: typeof record.document }
                    await pending
                    return { ...record, revision: 2, document: body.document }
                },
            },
        })
        logic.actions.changeDocument({ ...record.document, conclusion: 'First edit' })
        logic.actions.save()
        logic.actions.changeDocument({ ...record.document, conclusion: 'Edited while saving' })
        finish()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.record?.document.conclusion).toBe('First edit')
        expect(logic.values.document?.conclusion).toBe('Edited while saving')
        expect(logic.values.dirty).toBe(true)
        expect(logic.values.record?.revision).toBe(2)
    })

    it.each(['save', 'archive'] as const)('keeps the local document after a conflicting %s', async (action) => {
        useMocks({
            patch: { '/api/projects/:team_id/investigations/:id/': [409, { detail: 'Newer revision exists' }] },
        })
        const edited = { ...record.document, conclusion: 'Keep this evidence' }
        logic.actions.changeDocument(edited)
        await expectLogic(logic, () => logic.actions[action]()).toFinishAllListeners()
        expect(logic.values.document).toEqual(edited)
        expect(logic.values.dirty).toBe(true)
        expect(logic.values.conflict).toBe(true)
        expect(logic.values.busy).toBe(false)
    })

    it('marks a run saved when the API normalizes timestamp precision', async () => {
        const document = {
            ...record.document,
            runs: [{ id: 'run-1', at: '2026-11-01T00:00:00.123Z', conclusion: '', results: [] }],
        }
        useMocks({
            patch: {
                '/api/projects/:team_id/investigations/:id/': {
                    ...record,
                    revision: 2,
                    document: { ...document, runs: [{ ...document.runs[0], at: '2026-11-01T00:00:00.123000Z' }] },
                },
            },
        })
        logic.actions.changeDocument(document)
        await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()
        expect(logic.values.dirty).toBe(false)
        expect(logic.values.document).toEqual(document)
    })
})
