import { useEffect } from 'react'

import { queryClient } from '@/api/queryClient'

// Local Expo modules have no node_modules entry, so they are imported by path.
import { isAvailable } from '../../../modules/chart-widget'

import { startChartWidgetSync } from './chartWidgetSync'

export function useChartWidgetSync(): void {
    useEffect(() => {
        if (!isAvailable()) {
            return
        }
        return startChartWidgetSync(queryClient)
    }, [])
}
