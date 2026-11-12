import { useIsFocused } from 'expo-router'
import { useContext, useEffect, useId, useRef } from 'react'
import { BackHandler } from 'react-native'
import { OverlayDismissContext, useNavigationOverlayStore } from './overlayDismiss'

export function useOverlayBack(visible: boolean, onClose: () => void): void {
    const focused = useIsFocused()
    const key = useId()
    const setDismissal = useContext(OverlayDismissContext)?.set
    const close = useRef(onClose)
    useEffect(() => {
        close.current = onClose
    }, [onClose])

    useEffect(() => {
        if (!visible || !focused) {
            return
        }
        useNavigationOverlayStore.getState().set(key, true)
        setDismissal?.(key, () => close.current())
        const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
            close.current()
            return true
        })
        return () => {
            useNavigationOverlayStore.getState().set(key, false)
            setDismissal?.(key, null)
            subscription.remove()
        }
    }, [visible, focused, key, setDismissal])
}
