import type { ReactElement } from 'react'
import { Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ViewsIcon({ size = 22, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={4} y={4} width={6.5} height={9} rx={1.2} />
            <Rect x={13.5} y={4} width={6.5} height={5} rx={1.2} />
            <Rect x={13.5} y={12} width={6.5} height={8} rx={1.2} />
            <Rect x={4} y={16} width={6.5} height={4} rx={1.2} />
        </StrokeIcon>
    )
}
