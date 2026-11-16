import type { ReactElement } from 'react'
import Svg, { Path } from 'react-native-svg'

import { useColors } from '../theme'
import { LogomarkShapes } from './LogomarkShapes'
import { WORDMARK_PATH } from './wordmarkPath'

const VIEW_BOX_WIDTH = 160
const VIEW_BOX_HEIGHT = 28

interface PostHogLogoProps {
    height?: number
}

/** The landscape lockup: logomark plus wordmark. The brand guidelines forbid plain text beside the logomark. */
export function PostHogLogo({ height = 28 }: PostHogLogoProps): ReactElement {
    const { ink } = useColors()
    return (
        <Svg
            width={(height * VIEW_BOX_WIDTH) / VIEW_BOX_HEIGHT}
            height={height}
            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${VIEW_BOX_HEIGHT}`}
            accessibilityRole="image"
            accessibilityLabel="PostHog"
        >
            <LogomarkShapes />
            <Path fill={ink} d={WORDMARK_PATH} />
        </Svg>
    )
}
