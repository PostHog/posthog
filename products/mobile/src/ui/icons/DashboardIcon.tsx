import type { ReactElement } from 'react'
import { Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function DashboardIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={3.5} y={3.5} width={7} height={7} rx={1.5} />
            <Rect x={13.5} y={3.5} width={7} height={7} rx={1.5} />
            <Rect x={3.5} y={13.5} width={7} height={7} rx={1.5} />
            <Rect x={13.5} y={13.5} width={7} height={7} rx={1.5} />
        </StrokeIcon>
    )
}
