import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonRetentionMeanDropdown } from './LemonRetentionMeanDropdown'
import { QuillRetentionMeanDropdown } from './QuillRetentionMeanDropdown'

export type RetentionMeanType = 'simple' | 'weighted'

export function RetentionMeanDropdown(): JSX.Element | null {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillRetentionMeanDropdown /> : <LemonRetentionMeanDropdown />
}
