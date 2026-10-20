import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonRetentionReferencePicker } from './LemonRetentionReferencePicker'
import { QuillRetentionReferencePicker } from './QuillRetentionReferencePicker'

export function RetentionReferencePicker(): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillRetentionReferencePicker /> : <LemonRetentionReferencePicker />
}
