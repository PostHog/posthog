import type { ReactElement } from 'react'

import { WorldMapCanvas, type WorldMapProps } from './WorldMapCanvas'

export function WorldMap(props: WorldMapProps): ReactElement {
    return <WorldMapCanvas {...props} />
}
