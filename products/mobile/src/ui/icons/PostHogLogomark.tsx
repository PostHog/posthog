import type { ReactElement } from 'react'
import Svg from 'react-native-svg'

import { LogomarkShapes } from './LogomarkShapes'

const VIEW_BOX_WIDTH = 52
const VIEW_BOX_HEIGHT = 28

interface PostHogLogomarkProps {
    height?: number
}

export function PostHogLogomark({ height = 18 }: PostHogLogomarkProps): ReactElement {
    return (
        <Svg
            width={(height * VIEW_BOX_WIDTH) / VIEW_BOX_HEIGHT}
            height={height}
            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${VIEW_BOX_HEIGHT}`}
            accessibilityRole="image"
            accessibilityLabel="PostHog"
        >
            <LogomarkShapes />
        </Svg>
    )
}
