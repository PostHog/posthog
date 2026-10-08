import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { urls } from 'scenes/urls'

import { RetentionRulesProduct } from 'products/logs/frontend/components/LogsRetention/retentionRulesProduct'
import {
    tracingRetentionRulesCreate,
    tracingRetentionRulesDestroy,
    tracingRetentionRulesList,
    tracingRetentionRulesPartialUpdate,
    tracingRetentionRulesReorderCreate,
    tracingRetentionRulesRetrieve,
    tracingRetentionRulesSuggestNameCreate,
} from 'products/tracing/frontend/generated/api'
import { tracingRetentionSettingsUrl } from 'products/tracing/frontend/tracingRetentionSettingsUrl'

export const TRACES_RETENTION_PRODUCT: RetentionRulesProduct = {
    source: 'spans',
    recordNoun: 'span',
    recordNounPlural: 'spans',
    api: {
        list: (projectId) => tracingRetentionRulesList(projectId),
        create: (projectId, body) => tracingRetentionRulesCreate(projectId, body),
        retrieve: (projectId, id) => tracingRetentionRulesRetrieve(projectId, id),
        destroy: (projectId, id) => tracingRetentionRulesDestroy(projectId, id),
        partialUpdate: (projectId, id, body) => tracingRetentionRulesPartialUpdate(projectId, id, body),
        reorder: (projectId, body) => tracingRetentionRulesReorderCreate(projectId, body),
        suggestName: (projectId, body) => tracingRetentionRulesSuggestNameCreate(projectId, body),
    },
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.Spans,
        TaxonomicFilterGroupType.SpanResourceAttributes,
        TaxonomicFilterGroupType.SpanAttributes,
    ],
    urls: {
        newRule: () => urls.tracingRetentionNew(),
        ruleDetail: (id) => urls.tracingRetentionDetail(id),
        settings: () => tracingRetentionSettingsUrl(),
    },
    // Traces have no bytes-volume preview endpoint yet.
    showVolumePreview: false,
}
