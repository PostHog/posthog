import { Canvas, Group, Path, Skia, type SkPath } from '@shopify/react-native-skia'
import { memo, type ReactElement, useMemo, useState } from 'react'
import { StyleSheet, View } from 'react-native'

import { useColors } from '@/ui/theme'

import { mapFill } from './mapColors'
import { fitMap, mapTransform, WORLD_ASPECT_RATIO } from './mapGeometry'
import { WORLD_PATHS } from './worldPaths'

const BORDER_WIDTH = 0.5

export interface WorldMapProps {
    /** Visitors per ISO 3166-1 alpha-2 code. */
    counts: Readonly<Record<string, number>>
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

/**
 * The world in Skia: land in the empty segment color, each country with visitors in blue by its share of the leader's
 * visitors, as the web's live map draws it. Memoized, so only a new read repaints it; the 10-second
 * stats updates and the read state changes on the screen around it do not.
 */
export const WorldMapCanvas = memo(function WorldMapCanvas({ counts, testID }: WorldMapProps): ReactElement {
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
    const drawing =
        width > 0 ? (
            <Canvas style={StyleSheet.absoluteFill}>
                <Group transform={mapTransform(fit)}>
                    <Path path={land} color={colors.segmentEmpty} />
                    {fills.map(({ code, path, color }) => (
                        <Path key={code} path={path} color={color} />
                    ))}
                    <Path path={land} style="stroke" strokeWidth={BORDER_WIDTH / fit.scale} color={colors.surface} />
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
            {drawing}
        </View>
    )
})
