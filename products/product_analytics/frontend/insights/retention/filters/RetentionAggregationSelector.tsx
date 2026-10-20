import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonRetentionAggregationSelector } from './LemonRetentionAggregationSelector'
import { QuillRetentionAggregationSelector } from './QuillRetentionAggregationSelector'

export function RetentionAggregationSelector(): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillRetentionAggregationSelector /> : <LemonRetentionAggregationSelector />
}
