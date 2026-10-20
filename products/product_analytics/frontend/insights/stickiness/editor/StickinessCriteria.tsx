import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonStickinessCriteria } from './LemonStickinessCriteria'
import { QuillStickinessCriteria } from './QuillStickinessCriteria'

export function StickinessCriteria(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillStickinessCriteria {...props} /> : <LemonStickinessCriteria {...props} />
}
