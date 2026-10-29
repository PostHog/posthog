import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { useColors } from '../theme'
import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

interface PinIconProps extends IconProps {
    /** The filled head marks a pinned view. */
    filled?: boolean
}

export function PinIcon({
    size = 22,
    color: colorProp,
    strokeWidth = 1.9,
    filled = false,
}: PinIconProps): ReactElement {
    const colors = useColors()
    const color = colorProp ?? colors.ink
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            {filled ? (
                <>
                    <Path d="M10 3.5v5L6.5 13h11L14 8.5v-5z" fill={color} />
                    <Path d="M8.5 3.5h7M12 13v8" />
                </>
            ) : (
                // On unpin, React reuses the filled Path and removes its `fill`. react-native-svg then draws the
                // default black fill, not the Svg's `none`, so the outline sets it.
                <Path d="M8.5 3.5h7M10 3.5v5L6.5 13h11L14 8.5v-5M12 13v8" fill="none" />
            )}
        </StrokeIcon>
    )
}
