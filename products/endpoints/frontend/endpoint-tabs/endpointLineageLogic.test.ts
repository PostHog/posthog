import api, { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointLineageLogic } from './endpointLineageLogic'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        constructor(message?: string, status?: number) {
            super(message)
            this.status = status
        }
    }
    return {
        __esModule: true,
        default: { dataModelingNodes: { lineage: jest.fn() } },
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

describe('endpointLineageLogic', () => {
    let logic: ReturnType<typeof endpointLineageLogic.build>

    const lineageRequest = (): jest.Mock => api.dataModelingNodes.lineage as unknown as jest.Mock

    const mountLogic = async (): Promise<void> => {
        logic = endpointLineageLogic({ savedQueryId: 'saved-query-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        lineageRequest().mockReset()
        initKeaTests()
    })

    it('asks for the lineage of the endpoint it was given and marks that endpoint node', async () => {
        lineageRequest().mockResolvedValue({
            nodes: [
                { id: 'node-upstream', saved_query_id: 'saved-query-0' },
                { id: 'node-self', saved_query_id: 'saved-query-1' },
            ],
            edges: [],
        })

        await mountLogic()

        expect(lineageRequest()).toHaveBeenCalledWith({ savedQueryId: 'saved-query-1' })
        expect(logic.values.currentNodeId).toBe('node-self')
        expect(logic.values.lineageMissing).toBe(false)
        expect(logic.values.lineageFailed).toBe(false)
    })

    const failures: [string, number | undefined, boolean, boolean][] = [
        ['a model that has no lineage node yet', 404, true, false],
        ['a request that broke', 500, false, true],
        ['a request that broke without a status', undefined, false, true],
    ]

    it.each(failures)('tells %s apart from the other outcome', async (_, status, missing, failed) => {
        lineageRequest().mockRejectedValue(new ApiError('nope', status))

        await mountLogic()

        expect(logic.values.lineage).toBeNull()
        expect(logic.values.lineageMissing).toBe(missing)
        expect(logic.values.lineageFailed).toBe(failed)
    })

    it('clears the error and asks again when the retry runs', async () => {
        lineageRequest().mockRejectedValueOnce(new ApiError('nope', 500))
        await mountLogic()
        expect(logic.values.lineageFailed).toBe(true)

        lineageRequest().mockResolvedValue({
            nodes: [{ id: 'node-self', saved_query_id: 'saved-query-1' }],
            edges: [],
        })
        logic.actions.loadLineage()
        await expectLogic(logic).toFinishAllListeners()

        expect(lineageRequest()).toHaveBeenCalledTimes(2)
        expect(logic.values.lineageFailed).toBe(false)
        expect(logic.values.currentNodeId).toBe('node-self')
    })
})
