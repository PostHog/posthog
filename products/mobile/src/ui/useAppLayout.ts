import { Platform, useWindowDimensions } from 'react-native'
import { useReservedRegions } from 'react-native-reserved-regions'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { adaptiveLayout } from './adaptiveLayout'

export function useAppLayout(): ReturnType<typeof adaptiveLayout> {
    const { width, height } = useWindowDimensions()
    const { left, right } = useSafeAreaInsets()
    const regions = useReservedRegions()
    return adaptiveLayout(width, height, left, right, regions, Platform.OS === 'ios')
}
