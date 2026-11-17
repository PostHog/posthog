import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InvestigationDocument, newInvestigation } from './investigationDocument'
import { investigationLogic } from './investigationLogic'

describe('investigationLogic', () => {
    let logic: ReturnType<typeof investigationLogic.build>
    let persisted: InvestigationDocument[]
    const document: InvestigationDocument = {
        ...newInvestigation('What changed?'),
        evidence: [
            {
                id: 'metric',
                reference: 1,
                title: 'Metric',
                kind: 'query',
                sql: 'SELECT 42 AS metric',
                note: '',
                url: '',
            },
        ],
        nextEvidenceNumber: 2,
    }

    beforeEach(() => {
        initKeaTests()
        persisted = []
        logic = investigationLogic({
            scope: 'test-investigation',
            document,
            editable: true,
            onChange: (value) => persisted.push(value),
        })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('records actual query results with their definition and preserves edits made during a run', async () => {
        let complete: () => void = () => {}
        const responseReady = new Promise<void>((resolve) => {
            complete = resolve
        })
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async () => {
                    await responseReady
                    return { columns: ['metric'], results: [[42]], hasMore: false }
                },
            },
        })
        logic.actions.runEvidence()
        expect(logic.values.running).toBe(true)
        logic.actions.changeDocument({ ...logic.values.document, conclusion: 'An edit during execution' })
        complete()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.running).toBe(false)
        expect(persisted.at(-1)).toMatchObject({
            conclusion: 'An edit during execution',
            runs: [
                {
                    conclusion: '',
                    results: [{ evidenceId: 'metric', sql: 'SELECT 42 AS metric', rows: [[42]], error: null }],
                },
            ],
        })
    })

    it('retains failures as failed evidence instead of silently keeping an older successful result', async () => {
        useMocks({ post: { '/api/environments/:team_id/query/:kind': [400, { detail: 'Unknown field conversion' }] } })
        await expectLogic(logic, () => logic.actions.runEvidence()).toFinishAllListeners()
        expect(logic.values.running).toBe(false)
        expect(logic.values.document.runs[0].results[0]).toMatchObject({
            rows: [],
            error: expect.stringContaining('Unknown field'),
        })
    })

    it('cancels a pending run without persisting partial evidence', async () => {
        let complete: () => void = () => {}
        const responseReady = new Promise<void>((resolve) => {
            complete = resolve
        })
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async () => {
                    await responseReady
                    return { columns: ['metric'], results: [[42]] }
                },
            },
        })
        logic.actions.runEvidence()
        logic.actions.cancelRun()
        complete()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.document.runs).toEqual([])
        expect(persisted).toEqual([])
        expect(logic.values.running).toBe(false)
    })

    it('cannot change or execute an investigation through a read-only host', async () => {
        logic.unmount()
        logic = investigationLogic({
            scope: 'read-only',
            document,
            editable: false,
            onChange: (value) => persisted.push(value),
        })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.changeDocument({ ...document, conclusion: 'Not allowed' })
            logic.actions.runEvidence()
        }).toFinishAllListeners()
        expect(logic.values.document).toEqual(document)
        expect(persisted).toEqual([])
    })
})
