import { useVerticalBarEdgeIOS } from 'expo-status-bar'
import { Platform } from 'react-native'

export function useNativeRail(): boolean {
    const edge = useVerticalBarEdgeIOS()
    return Platform.OS === 'ios' && (edge === 'leading' || edge === 'trailing')
}
