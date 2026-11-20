import AsyncStorage from '@react-native-async-storage/async-storage'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import type { BarLayout } from '@/ui/chart/types'

interface ChartPreferencesState {
    barLayout: BarLayout | null
    setBarLayout: (layout: BarLayout) => void
}

export const useChartPreferences = create<ChartPreferencesState>()(
    persist(
        (set) => ({
            barLayout: null,
            setBarLayout: (barLayout) => set({ barLayout }),
        }),
        {
            name: 'views-chart-preferences:v1',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ barLayout: state.barLayout }),
        }
    )
)
