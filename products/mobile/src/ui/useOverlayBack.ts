import { useEffect, useRef } from 'react'
import { BackHandler } from 'react-native'

export function useOverlayBack(visible: boolean, onClose: () => void): void {
    const close = useRef(onClose)
    useEffect(() => {
        close.current = onClose
    }, [onClose])

    useEffect(() => {
        if (!visible) {
            return
        }
        const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
            close.current()
            return true
        })
        return () => subscription.remove()
    }, [visible])
}
