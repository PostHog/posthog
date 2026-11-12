import { type ReactElement, useId } from 'react'
import { type SvgProps, SvgXml } from 'react-native-svg'

export function BrandSvg({ xml, ...props }: SvgProps & { xml: string }): ReactElement {
    const prefix = useId().replace(/[^A-Za-z0-9]/g, '')
    const scopedXml = xml.replace(/(id="|url\(#)([\w-]+)/g, `$1${prefix}-$2`)
    return <SvgXml xml={scopedXml} {...props} />
}
