import {
    createContext,
    Fragment,
    type ReactElement,
    type ReactNode,
    useCallback,
    useContext,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from 'react'
import type { ViewInstance } from 'react-native'
import { StyleSheet, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import type { DisplayRect } from './displayRegions'
import { OverlayDismissContext } from './overlayDismiss'
import { OverlayFrameContext } from './overlayFrame'

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
    const ref = useRef<ViewInstance>(null)
    const { width, height } = useWindowDimensions()
    const { left, right, top, bottom } = useSafeAreaInsets()
    const [frame, setFrame] = useState<DisplayRect | null>(null)
    const measure = useCallback(() => {
        ref.current?.measureInWindow((x, y, width, height) => {
            setFrame((previous) =>
                previous?.x === x && previous.y === y && previous.width === width && previous.height === height
                    ? previous
                    : { x, y, width, height }
            )
        })
    }, [])
    // biome-ignore lint/correctness/useExhaustiveDependencies: safe-area changes can move the host without changing its size.
    useLayoutEffect(measure, [measure, width, height, left, right, top, bottom])
    const [dismissals, setDismissals] = useState<ReadonlyMap<string, () => void>>(() => new Map())
    const setDismissal = useCallback((key: string, close: (() => void) | null): void => {
        setDismissals((previous) => {
            if (close === null && !previous.has(key)) return previous
            const next = new Map(previous)
            if (close) next.set(key, close)
            else next.delete(key)
            return next
        })
    }, [])
    const dismissalContext = useMemo(
        () => ({ set: setDismissal, close: [...dismissals.values()].at(-1) ?? null }),
        [setDismissal, dismissals]
    )
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
            <OverlayDismissContext.Provider value={dismissalContext}>
                <OverlayFrameContext.Provider value={frame}>
                    <View ref={ref} onLayout={measure} collapsable={false} style={styles.root}>
                        {children}
                        <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
                            {[...nodes].map(([key, node]) => (
                                <Fragment key={key}>{node}</Fragment>
                            ))}
                        </View>
                    </View>
                </OverlayFrameContext.Provider>
            </OverlayDismissContext.Provider>
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
