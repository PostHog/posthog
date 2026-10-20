import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonCumulativeStickinessFilter } from './LemonCumulativeStickinessFilter'
import { QuillCumulativeStickinessFilter } from './QuillCumulativeStickinessFilter'

export function CumulativeStickinessFilter(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? (
        <QuillCumulativeStickinessFilter {...props} />
    ) : (
        <LemonCumulativeStickinessFilter {...props} />
    )
}
