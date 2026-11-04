import {
    createContext,
    Fragment,
    type ReactElement,
    type ReactNode,
    useCallback,
    useContext,
    useId,
    useLayoutEffect,
    useState,
} from 'react'
import { StyleSheet, View } from 'react-native'

type SetOverlay = (key: string, node: ReactNode | null) => void

const OverlayContext = createContext<SetOverlay | null>(null)

interface OverlayHostProps {
    children: ReactNode
}

/**
 * Draws every `OverlayPortal` below it in a layer after `children`, so overlays cover chrome that a navigator draws
 * after its scenes, such as a tab bar.
 */
export function OverlayHost({ children }: OverlayHostProps): ReactElement {
    const [nodes, setNodes] = useState<ReadonlyMap<string, ReactNode>>(() => new Map())
    const setOverlay = useCallback<SetOverlay>((key, node) => {
        setNodes((previous) => {
            if (node === null && !previous.has(key)) {
                return previous
            }
            // `Map.set` keeps an existing key in place, so an overlay keeps its stacking order when it re-renders.
            const next = new Map(previous)
            if (node === null) {
                next.delete(key)
            } else {
                next.set(key, node)
            }
            return next
        })
    }, [])

    return (
        <OverlayContext.Provider value={setOverlay}>
            <View style={styles.root}>
                {children}
                <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
                    {[...nodes].map(([key, node]) => (
                        <Fragment key={key}>{node}</Fragment>
                    ))}
                </View>
            </View>
        </OverlayContext.Provider>
    )
}

interface OverlayPortalProps {
    children: ReactNode
}

export function OverlayPortal({ children }: OverlayPortalProps): ReactElement | null {
    const setOverlay = useContext(OverlayContext)
    const key = useId()

    useLayoutEffect(() => {
        setOverlay?.(key, children)
    }, [setOverlay, key, children])

    useLayoutEffect(() => {
        if (!setOverlay) {
            return undefined
        }
        return () => setOverlay(key, null)
    }, [setOverlay, key])

    if (!setOverlay) {
        return <>{children}</>
    }
    return null
}

const styles = StyleSheet.create({
    root: {
        flex: 1,
    },
})
