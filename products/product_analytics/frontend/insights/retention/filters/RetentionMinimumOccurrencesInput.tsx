import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonRetentionMinimumOccurrencesInput } from './LemonRetentionMinimumOccurrencesInput'
import { QuillRetentionMinimumOccurrencesInput } from './QuillRetentionMinimumOccurrencesInput'

export function RetentionMinimumOccurrencesInput(): JSX.Element | null {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillRetentionMinimumOccurrencesInput /> : <LemonRetentionMinimumOccurrencesInput />
}
