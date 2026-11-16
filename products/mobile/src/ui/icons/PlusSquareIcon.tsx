import type { ReactElement } from 'react'
import { Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function PlusSquareIcon({ size = 15, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={4} y={4} width={16} height={16} rx={3} />
            <Path d="M8 12h8M12 8v8" />
        </StrokeIcon>
    )
}
