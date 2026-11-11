import { useNavigation } from 'expo-router'
import type { NativeStackNavigationProp } from 'expo-router/native-stack'
import { type ParamListBase, useIsFocused } from 'expo-router/react-navigation'
import { useLayoutEffect, useState } from 'react'
import { Platform } from 'react-native'

export function useChatAutoFocus(): boolean {
    const navigation = useNavigation<NativeStackNavigationProp<ParamListBase>>()
    const focused = useIsFocused()
    const [opened, setOpened] = useState(Platform.OS === 'web')

    useLayoutEffect(() => {
        const end = navigation.addListener('transitionEnd', ({ data }) => {
            if (!data.closing) {
                setOpened(true)
            }
        })
        const blur = navigation.addListener('blur', () => setOpened(Platform.OS === 'web'))
        return () => {
            end()
            blur()
        }
    }, [navigation])

    return opened && focused
}
