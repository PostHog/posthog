import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { InsightLogicProps } from '~/types'

import { LemonAggregationSelect } from './LemonAggregationSelect'
import { QuillAggregationSelect } from './QuillAggregationSelect'

export type AggregationSelectProps = {
    insightProps: InsightLogicProps
    className?: string
    hogqlAvailable?: boolean
    value?: string
}

export function AggregationSelect(props: AggregationSelectProps): JSX.Element | null {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillAggregationSelect {...props} /> : <LemonAggregationSelect {...props} />
}
