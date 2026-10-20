import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonExclusionRowSuffix } from './LemonExclusionRowSuffix'
import { QuillExclusionRowSuffix } from './QuillExclusionRowSuffix'

export type ExclusionRowSuffixProps = {
    index: number
    onClose?: () => void
    typeKey: string
}

export function ExclusionRowSuffix(props: ExclusionRowSuffixProps): JSX.Element | null {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillExclusionRowSuffix {...props} /> : <LemonExclusionRowSuffix {...props} />
}
