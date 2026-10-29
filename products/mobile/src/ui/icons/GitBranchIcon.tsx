import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function GitBranchIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={6} cy={5} r={2.2} />
            <Circle cx={6} cy={19} r={2.2} />
            <Circle cx={18} cy={8} r={2.2} />
            <Path d="M6 7.2v9.6" />
            <Path d="M18 10.2c0 4-12 2.5-12 6.6" />
        </StrokeIcon>
    )
}
