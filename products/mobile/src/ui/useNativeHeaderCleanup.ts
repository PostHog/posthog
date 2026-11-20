import { useNavigation } from 'expo-router'
import { useLayoutEffect } from 'react'

export function useNativeHeaderCleanup(): void {
    const navigation = useNavigation()
    // Stack.Screen leaves its options set after unmount, including when the system moves the rail.
    useLayoutEffect(() => () => navigation.setOptions({ headerShown: false, gestureEnabled: true }), [navigation])
}
