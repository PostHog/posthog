import type { ReactElement } from 'react'

import { useColorSchemeName } from '../theme'
import { BrandSvg } from './BrandSvg'
import brandLogos from './brandLogos.json'

interface PostHogLogoProps {
    height?: number
}

export function PostHogLogo({ height = 28 }: PostHogLogoProps): ReactElement {
    return (
        <BrandSvg
            xml={brandLogos[useColorSchemeName()].landscape}
            width={(height * 160) / 28}
            height={height}
            accessibilityRole="image"
            accessibilityLabel="PostHog"
        />
    )
}
