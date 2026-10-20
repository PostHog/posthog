import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonRetentionCumulativeButton } from './LemonRetentionCumulativeButton'
import { QuillRetentionCumulativeButton } from './QuillRetentionCumulativeButton'

export function RetentionCumulativeButton(): JSX.Element | null {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillRetentionCumulativeButton /> : <LemonRetentionCumulativeButton />
}
