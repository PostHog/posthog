import posthog from 'posthog-js'

import { FunnelsActorsQuery, InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { ActorType } from '~/types'

type EmailBucket = '0' | '1-9' | '10-99' | '100+'

function isPersonFunnelDropOff(query: FunnelsActorsQuery | InsightActorsQuery | null): boolean {
    return (
        query?.kind === NodeKind.FunnelsActorsQuery &&
        (query.funnelStep ?? 0) < 0 &&
        query.source.aggregation_group_type_index == null &&
        !query.source.funnelsFilter?.funnelAggregateByHogQL
    )
}

function hasEmailAddress(actor: ActorType): boolean {
    const email = actor.properties?.email
    return typeof email === 'string' && email.includes('@')
}

function emailBucket(peopleWithEmail: number): EmailBucket {
    if (peopleWithEmail >= 100) {
        return '100+'
    }
    if (peopleWithEmail >= 10) {
        return '10-99'
    }
    return peopleWithEmail > 0 ? '1-9' : '0'
}

export function captureFunnelDropOffAudienceChecked(
    query: FunnelsActorsQuery | InsightActorsQuery | null,
    firstPage: ActorType[]
): void {
    if (!isPersonFunnelDropOff(query)) {
        return
    }
    posthog.capture('funnel drop-off audience checked', {
        has_results: firstPage.length > 0,
        with_email_bucket: emailBucket(firstPage.filter(hasEmailAddress).length),
    })
}
