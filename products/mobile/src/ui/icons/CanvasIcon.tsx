import type { ReactElement } from 'react'
import { Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function CanvasIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={3.5} y={4} width={17} height={12} rx={2} />
            <Path d="M12 16v4M8.5 20h7" />
            <Path d="M7.5 12.5l3-3 2.5 2 3.5-4" />
        </StrokeIcon>
    )
}
