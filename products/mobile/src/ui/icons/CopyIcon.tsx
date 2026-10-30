import type { ReactElement } from 'react'
import { Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function CopyIcon({ size = 16, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={9} y={9} width={12} height={12} rx={2} />
            <Path d="M5 15V5a2 2 0 0 1 2-2h10" />
        </StrokeIcon>
    )
}
