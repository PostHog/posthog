import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonFunnelConversionWindowFilter } from './LemonFunnelConversionWindowFilter'
import { QuillFunnelConversionWindowFilter } from './QuillFunnelConversionWindowFilter'

export function FunnelConversionWindowFilter(props: Pick<EditorFilterProps, 'insightProps'>): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? (
        <QuillFunnelConversionWindowFilter {...props} />
    ) : (
        <LemonFunnelConversionWindowFilter {...props} />
    )
}
