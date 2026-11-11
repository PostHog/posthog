import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingRecommendationsSourceMapsExamplesRetrieve } from '../../../generated/api'
import type { MissingSymbolsExamplesApi } from '../../../generated/api.schemas'
import { sourceMapsExamplesLogic } from './sourceMapsExamplesLogic'

jest.mock('../../../generated/api', () => ({
    errorTrackingRecommendationsSourceMapsExamplesRetrieve: jest.fn(),
}))

const mockRetrieve = jest.mocked(errorTrackingRecommendationsSourceMapsExamplesRetrieve)

function examplesFor(platform: MissingSymbolsExamplesApi['platform']): MissingSymbolsExamplesApi {
    return { platform, lookback_hours: 24, exceptions_loaded: true, results: [] }
}

describe('sourceMapsExamplesLogic', () => {
    let logic: ReturnType<typeof sourceMapsExamplesLogic.build>

    beforeEach(() => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: 2, project_id: 1 })
        mockRetrieve.mockReset()
        logic = sourceMapsExamplesLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('loads the examples of the current environment, not of its project', async () => {
        mockRetrieve.mockResolvedValue(examplesFor('javascript'))

        await expectLogic(logic, () => logic.actions.openExamples('javascript')).toDispatchActions([
            'loadExamplesSuccess',
        ])

        expect(mockRetrieve).toHaveBeenCalledWith('2', { platform: 'javascript' })
    })

    it.each([
        ['succeeds', (): Promise<MissingSymbolsExamplesApi> => Promise.resolve(examplesFor('javascript'))],
        ['fails', (): Promise<MissingSymbolsExamplesApi> => Promise.reject(new Error('Gateway timeout'))],
    ])('ignores a superseded request that %s after the newer one', async (_, settleSuperseded) => {
        let releaseSuperseded: () => void = () => {}
        const superseded = new Promise<MissingSymbolsExamplesApi>((resolve, reject) => {
            releaseSuperseded = () => void settleSuperseded().then(resolve, reject)
        })
        mockRetrieve.mockReturnValueOnce(superseded).mockResolvedValueOnce(examplesFor('java'))

        await expectLogic(logic, () => {
            logic.actions.openExamples('javascript')
            logic.actions.closeExamples()
            logic.actions.openExamples('java')
        }).toDispatchActions(['loadExamplesSuccess'])
        releaseSuperseded()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(logic.values.examples).toEqual(examplesFor('java'))
        expect(logic.values.examplesFailed).toBe(false)
    })
})
