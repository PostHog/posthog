import { syncHedgehogWidget } from './useHedgehogWidgetSync'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
const mockSetChoreography = jest.fn()
jest.mock('../../../modules/hedgehog-widget', () => ({
    isAvailable: () => true,
    setChoreography: (json: string) => mockSetChoreography(json),
}))

describe('syncHedgehogWidget', () => {
    it('writes the choreography once per UTC day, even when launch and foreground race', async () => {
        const morning = new Date('2026-10-13T08:00:00Z')
        await Promise.all([syncHedgehogWidget(morning), syncHedgehogWidget(morning)])
        await syncHedgehogWidget(new Date('2026-10-13T21:00:00Z'))

        expect(mockSetChoreography).toHaveBeenCalledTimes(1)
        expect(JSON.parse(mockSetChoreography.mock.calls[0][0])).toMatchObject({
            seed: 20261013,
            startsAt: '2026-10-13T00:00:00.000Z',
        })

        await syncHedgehogWidget(new Date('2026-10-14T00:05:00Z'))

        expect(mockSetChoreography).toHaveBeenCalledTimes(2)
        expect(JSON.parse(mockSetChoreography.mock.calls[1][0])).toMatchObject({ seed: 20261014 })
    })
})
