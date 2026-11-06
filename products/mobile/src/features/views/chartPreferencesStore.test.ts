import AsyncStorage from '@react-native-async-storage/async-storage'

import { useChartPreferences } from './chartPreferencesStore'

const STORAGE_KEY = 'views-chart-preferences:v1'

test.each(['grouped', 'stacked'] as const)('restores the %s bar preference after reloading storage', async (layout) => {
    await useChartPreferences.persist.rehydrate()
    useChartPreferences.getState().setBarLayout(layout)
    const stored = await AsyncStorage.getItem(STORAGE_KEY)
    expect(stored).not.toBeNull()

    useChartPreferences.setState({ barLayout: null })
    await AsyncStorage.setItem(STORAGE_KEY, stored as string)
    await useChartPreferences.persist.rehydrate()

    expect(useChartPreferences.getState().barLayout).toBe(layout)
})
