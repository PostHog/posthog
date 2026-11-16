import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { FullScreenChart } from '@/features/views/fullScreen/FullScreenChart'
import { queryKeyParam } from '@/features/views/viewRoutes'

export default function ChartRoute(): ReactElement {
    const { shortId, key } = useLocalSearchParams<{ shortId: string; key?: string }>()
    return <FullScreenChart shortId={shortId ?? ''} queryKey={queryKeyParam(key)} />
}
