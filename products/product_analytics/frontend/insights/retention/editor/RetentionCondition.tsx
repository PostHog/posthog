import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonRetentionCondition } from './LemonRetentionCondition'
import { QuillRetentionCondition } from './QuillRetentionCondition'

export function RetentionCondition(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillRetentionCondition {...props} /> : <LemonRetentionCondition {...props} />
}
