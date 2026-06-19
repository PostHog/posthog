import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from '~/lib/api'

import { signalsReportsLinkedReportsRetrieve } from '../../../../../signals/frontend/generated/api'
import type { ErrorTrackingLinkedReportApi } from '../../../../../signals/frontend/generated/api.schemas'
import type { relatedInboxReportsLogicType } from './relatedInboxReportsLogicType'

export interface RelatedInboxReportsLogicProps {
    issueId: string
}

// The signals API tags error tracking signals with this source product. The reverse
// lookup walks that link back from an issue to the inbox report(s) it grouped into.
const ERROR_TRACKING_SOURCE_PRODUCT = 'error_tracking'

export const relatedInboxReportsLogic = kea<relatedInboxReportsLogicType>([
    path((key) => [
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingIssueScene',
        'ScenePanel',
        'relatedInboxReportsLogic',
        key,
    ]),
    props({} as RelatedInboxReportsLogicProps),
    key((props) => props.issueId),

    loaders(({ props }) => ({
        relatedReports: [
            [] as ErrorTrackingLinkedReportApi[],
            {
                // Lazily fetched on mount so the issue list doesn't fan out a request per row.
                loadRelatedReports: async () => {
                    return await signalsReportsLinkedReportsRetrieve(String(ApiConfig.getCurrentTeamId()), {
                        source_product: ERROR_TRACKING_SOURCE_PRODUCT,
                        source_id: props.issueId,
                    })
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadRelatedReports()
    }),
])
