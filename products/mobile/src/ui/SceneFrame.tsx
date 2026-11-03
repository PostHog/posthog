import { type ReactElement, type ReactNode, useCallback, useState } from 'react'
import { type LayoutChangeEvent, type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native'

import { SceneDimensionsContext } from './sceneDimensions'
import { useSceneDimensions } from './useSceneDimensions'

export function SceneFrame({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }): ReactElement {
    const parent = useSceneDimensions()
    const [size, setSize] = useState<{ width: number; height: number } | null>(null)
    const measure = useCallback(({ nativeEvent: { layout } }: LayoutChangeEvent): void => {
        setSize((previous) =>
            previous?.width === layout.width && previous.height === layout.height
                ? previous
                : { width: layout.width, height: layout.height }
        )
    }, [])
    return (
        <View style={[styles.frame, style]} onLayout={measure}>
            <SceneDimensionsContext.Provider value={size ?? parent}>{children}</SceneDimensionsContext.Provider>
        </View>
    )
}

const styles = StyleSheet.create({ frame: { flex: 1, minWidth: 0, minHeight: 0 } })
