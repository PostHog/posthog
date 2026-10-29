import AsyncStorage from '@react-native-async-storage/async-storage'

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
    beforeEach(async () => {
        await AsyncStorage.clear()
        mockSetChoreography.mockClear()
    })

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

    it.each(['20261013', '2:20261013', '3:20261013'])(
        'upgrades the same day script after an older sync stamp %s',
        async (stamp) => {
            await AsyncStorage.setItem('hedgehog_widget_seed', stamp)

            await syncHedgehogWidget(new Date('2026-10-13T08:00:00Z'))

            expect(mockSetChoreography).toHaveBeenCalledTimes(1)
            expect(JSON.parse(mockSetChoreography.mock.calls[0][0])).toMatchObject({ seed: 20261013, keyframeSec: 2 })
        }
    )
})
