import type { ReactElement } from 'react'
import type { SvgProps } from 'react-native-svg'

import { useColorSchemeName } from '../theme'
import { BrandSvg } from './BrandSvg'
import brandLogos from './brandLogos.json'

export type LogomarkPart = keyof typeof brandLogos.light.parts

export function LogomarkShapes({
    height,
    part,
    ...props
}: Pick<SvgProps, 'accessibilityRole' | 'accessibilityLabel'> & {
    height: number
    part?: LogomarkPart
}): ReactElement {
    const logo = brandLogos[useColorSchemeName()]
    return (
        <BrandSvg xml={part ? logo.parts[part] : logo.logomark} width={(height * 52) / 28} height={height} {...props} />
    )
}
