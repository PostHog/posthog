import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonFunnelVizType } from './LemonFunnelVizType'
import { QuillFunnelVizType } from './QuillFunnelVizType'

export function FunnelVizType(props: Pick<EditorFilterProps, 'insightProps'>): JSX.Element | null {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillFunnelVizType {...props} /> : <LemonFunnelVizType {...props} />
}
