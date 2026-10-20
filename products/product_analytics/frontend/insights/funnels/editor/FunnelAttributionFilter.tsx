import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonFunnelAttribution } from './LemonFunnelAttribution'
import { QuillFunnelAttribution } from './QuillFunnelAttribution'

export function FunnelAttribution(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillFunnelAttribution {...props} /> : <LemonFunnelAttribution {...props} />
}
