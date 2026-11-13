import { Canvas, Group, Path, Skia, type SkPath } from '@shopify/react-native-skia'
import { memo, type ReactElement, useMemo, useState } from 'react'
import { type GestureResponderEvent, Pressable, StyleSheet, View } from 'react-native'

import { useColors } from '@/ui/theme'

import { mapFill } from './mapColors'
import { fitMap, mapTransform, pickCountry, toMapPoint, WORLD_ASPECT_RATIO } from './mapGeometry'
import { WORLD_PATHS } from './worldPaths'

/** How far from a tap, in points, a small country still counts as tapped. */
const TAP_SLOP = 12
const BORDER_WIDTH = 0.5
const SELECTED_WIDTH = 2

export interface WorldMapProps {
    /** Visitors per ISO 3166-1 alpha-2 code. */
    counts: Readonly<Record<string, number>>
    selected?: string | null
    /** Gets the country with visitors under a tap, or null when the tap hits none. No handler, no tap target. */
    onSelect?: (code: string | null) => void
    testID?: string
}

interface WorldShapes {
    land: SkPath
    countries: ReadonlyMap<string, SkPath>
}

let shapes: WorldShapes | null = null

/** Parsed on the first draw and kept for the app session, because parsing every country's path takes a while. */
function worldShapes(): WorldShapes {
    if (!shapes) {
        const land = Skia.PathBuilder.Make()
        const countries = new Map<string, SkPath>()
        for (const [code, d] of Object.entries(WORLD_PATHS)) {
            const path = Skia.Path.MakeFromSVGString(d)
            if (path) {
                countries.set(code, path)
                land.addPath(path)
            }
        }
        shapes = { land: land.build(), countries }
    }
    return shapes
}

/** Where a tap landed in the box: `locationX` on native, `offsetX` on the web, where `onPress` gets a mouse event. */
function tapPoint(event: GestureResponderEvent): { x: number; y: number } | null {
    const native = event.nativeEvent as { locationX?: number; locationY?: number; offsetX?: number; offsetY?: number }
    const x = native.locationX ?? native.offsetX
    const y = native.locationY ?? native.offsetY
    return typeof x === 'number' && typeof y === 'number' ? { x, y } : null
}

/**
 * The world in Skia: land in the empty segment color, each country with visitors in blue by its share of the leader's
 * visitors, as the web's live map draws it. Memoized, so only a new read or a new selection repaints it; the 10-second
 * stats updates and the read state changes on the screen around it do not.
 */
export const WorldMapCanvas = memo(function WorldMapCanvas({
    counts,
    selected = null,
    onSelect,
    testID,
}: WorldMapProps): ReactElement {
    const colors = useColors()
    const [width, setWidth] = useState(0)
    const fit = useMemo(() => fitMap(width), [width])
    const { land, countries } = worldShapes()
    const fills = useMemo(() => {
        const max = Math.max(0, ...Object.values(counts))
        return Object.entries(counts).flatMap(([code, count]) => {
            const path = countries.get(code)
            return path && count > 0 ? [{ code, path, color: mapFill(colors, count / max) }] : []
        })
    }, [counts, countries, colors])
    const selectedPath = selected ? countries.get(selected) : undefined

    const onPress = (event: GestureResponderEvent): void => {
        const point = tapPoint(event)
        if (!onSelect || !point || fit.scale <= 0) {
            return
        }
        const hasVisitors = (code: string): boolean => (counts[code] ?? 0) > 0
        onSelect(pickCountry(countries, hasVisitors, toMapPoint(fit, point.x, point.y), TAP_SLOP / fit.scale))
    }

    const drawing =
        width > 0 ? (
            <Canvas style={StyleSheet.absoluteFill}>
                <Group transform={mapTransform(fit)}>
                    <Path path={land} color={colors.segmentEmpty} />
                    {fills.map(({ code, path, color }) => (
                        <Path key={code} path={path} color={color} />
                    ))}
                    <Path path={land} style="stroke" strokeWidth={BORDER_WIDTH / fit.scale} color={colors.surface} />
                    {selectedPath ? (
                        <Path
                            path={selectedPath}
                            style="stroke"
                            strokeWidth={SELECTED_WIDTH / fit.scale}
                            strokeJoin="round"
                            color={colors.ink}
                        />
                    ) : null}
                </Group>
            </Canvas>
        ) : null
    return (
        <View
            style={{ aspectRatio: WORLD_ASPECT_RATIO }}
            onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            testID={testID}
        >
            {onSelect ? (
                // Not focusable: the map is hidden from assistive tech, and the card and the list rows are the keyboard
                // targets. Enter on the map would carry no tap point anyway.
                <Pressable onPress={onPress} focusable={false} style={StyleSheet.absoluteFill}>
                    {drawing}
                </Pressable>
            ) : (
                drawing
            )}
        </View>
    )
})
