import { useWindowDimensions } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { adaptiveLayout } from './adaptiveLayout'

export function useAppLayout(): ReturnType<typeof adaptiveLayout> {
    const { width, height } = useWindowDimensions()
    const { left, right } = useSafeAreaInsets()
    return adaptiveLayout(width, height, left, right)
}
