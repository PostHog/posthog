import { WithSkiaWeb } from '@shopify/react-native-skia/lib/module/web'
import type { ComponentType, ReactElement } from 'react'
import { View } from 'react-native'

import { WORLD_ASPECT_RATIO } from './mapGeometry'
import type { WorldMapProps } from './WorldMapCanvas'

// The same CanvasKit wasm the charts load (see MetricChart.web.tsx), copied to `public/` by `npx setup-skia-web public`.
const canvasKitOptions = { locateFile: (file: string): string => `/${file}` }

function loadCanvas(): Promise<{ default: ComponentType<WorldMapProps> }> {
    return import('./WorldMapCanvas').then((module) => ({ default: module.WorldMapCanvas }))
}

export function WorldMap(props: WorldMapProps): ReactElement {
    // A box of the map's size holds the layout while CanvasKit loads.
    const placeholder = <View style={{ aspectRatio: WORLD_ASPECT_RATIO }} testID={props.testID} />
    return (
        <WithSkiaWeb getComponent={loadCanvas} opts={canvasKitOptions} fallback={placeholder} componentProps={props} />
    )
}
