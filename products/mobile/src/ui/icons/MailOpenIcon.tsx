import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function MailOpenIcon({ size = 20, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M3 10.2 10.9 4.8a2 2 0 0 1 2.2 0L21 10.2V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
            <Path d="m3 10.2 9 6 9-6" />
        </StrokeIcon>
    )
}
