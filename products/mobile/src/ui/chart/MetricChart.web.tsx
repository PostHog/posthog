import { WithSkiaWeb } from '@shopify/react-native-skia/lib/module/web'
import type { ReactElement } from 'react'

import { useCanvasSlot } from './budget/ChartCanvasBudget'
import { MetricChartPlaceholder } from './MetricChartPlaceholder'
import type { MetricChartProps } from './types'

// CanvasKit is a large wasm file, so only a screen with a chart waits for it. `npx setup-skia-web public` (run by
// the `web` script) copies it to `public/`, which Expo serves at the site root.
const canvasKitOptions = { locateFile: (file: string): string => `/${file}` }

function loadCanvas(): Promise<{ default: (props: MetricChartProps) => ReactElement }> {
    return import('./MetricChartCanvas').then((module) => ({ default: module.MetricChartCanvas }))
}

export function MetricChart(props: MetricChartProps): ReactElement {
    // Browsers cap live WebGL contexts at about 16, so the budget matters on web as well.
    const mounted = useCanvasSlot(props.canvasSlot)
    if (!mounted) {
        return <MetricChartPlaceholder {...props} />
    }
    return (
        <WithSkiaWeb
            getComponent={loadCanvas}
            opts={canvasKitOptions}
            fallback={<MetricChartPlaceholder {...props} />}
            componentProps={props}
        />
    )
}
