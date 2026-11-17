import { BlurTargetView } from 'expo-blur'
import { createContext, type ReactElement, type ReactNode, type RefObject, useContext, useRef } from 'react'
import { StyleSheet, type ViewInstance } from 'react-native'

const BlurTargetContext = createContext<RefObject<ViewInstance | null> | undefined>(undefined)

export function useScreenBlurTarget(): RefObject<ViewInstance | null> | undefined {
    return useContext(BlurTargetContext)
}

export function ScreenBlur({ children, chrome }: { children: ReactNode; chrome: ReactNode }): ReactElement {
    const blurTarget = useRef<ViewInstance>(null)
    // The header stays outside its target so it cannot blur itself.
    return (
        <BlurTargetContext.Provider value={blurTarget}>
            <BlurTargetView ref={blurTarget} style={styles.content}>
                {children}
            </BlurTargetView>
            {chrome}
        </BlurTargetContext.Provider>
    )
}

const styles = StyleSheet.create({ content: { flex: 1, minWidth: 0, minHeight: 0 } })
