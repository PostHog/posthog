import { compactNumber, humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { type Noun } from '~/models/groupsModel'

import { type FunnelBarListDetail } from './useFunnelBarListDetail'

export interface FunnelBarListCountProps {
    count: number
    aggregationTargetLabel: Noun
    verb: string
    detail: FunnelBarListDetail
}

export function FunnelBarListCount({
    count,
    aggregationTargetLabel,
    verb,
    detail,
}: FunnelBarListCountProps): JSX.Element | null {
    if (detail === 'percentages') {
        return null
    }
    const noun = pluralize(count, aggregationTargetLabel.singular, aggregationTargetLabel.plural, false)
    if (detail === 'full') {
        return <span>{` (${humanFriendlyNumber(count)} ${noun}) ${verb}`}</span>
    }
    if (detail === 'nouns') {
        return <span>{` (${humanFriendlyNumber(count)} ${noun})`}</span>
    }
    return <span>{` (${detail === 'counts' ? humanFriendlyNumber(count) : compactNumber(count)})`}</span>
}
