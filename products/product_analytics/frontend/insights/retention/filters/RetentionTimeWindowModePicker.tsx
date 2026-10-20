import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonRetentionTimeWindowModePicker } from './LemonRetentionTimeWindowModePicker'
import { QuillRetentionTimeWindowModePicker } from './QuillRetentionTimeWindowModePicker'

export function RetentionTimeWindowModePicker(): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillRetentionTimeWindowModePicker /> : <LemonRetentionTimeWindowModePicker />
}
