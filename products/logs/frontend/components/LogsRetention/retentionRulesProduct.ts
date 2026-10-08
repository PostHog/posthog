import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { urls } from 'scenes/urls'

import {
    logsRetentionRulesCreate,
    logsRetentionRulesDestroy,
    logsRetentionRulesList,
    logsRetentionRulesPartialUpdate,
    logsRetentionRulesReorderCreate,
    logsRetentionRulesRetrieve,
    logsRetentionRulesSuggestNameCreate,
} from 'products/logs/frontend/generated/api'
import { LogsRetentionRuleApi } from 'products/logs/frontend/generated/api.schemas'
import { logsRetentionRulesSettingsUrl } from 'products/logs/frontend/logsRetentionRulesSettingsUrl'

// Request bodies come from the generated logs client. The traces client is generated from the same
// serializers, so assigning it to this descriptor fails to compile if the two routes ever diverge.
type CreateBody = Parameters<typeof logsRetentionRulesCreate>[1]
type PartialUpdateBody = NonNullable<Parameters<typeof logsRetentionRulesPartialUpdate>[2]>
type ReorderBody = Parameters<typeof logsRetentionRulesReorderCreate>[1]
type SuggestNameBody = Parameters<typeof logsRetentionRulesSuggestNameCreate>[1]

/**
 * What separates one product's retention rules from another's.
 *
 * Everything that does differ — the API route, the filter vocabulary, the scene URLs and the noun
 * in the copy — is collected here, so both products drive the same components and logics.
 */
export interface RetentionRulesProduct {
    /** Record kind: `logs` for `LogsRetentionRule`, `spans` for `TracesRetentionRule`. Also the kea logic key. */
    source: 'logs' | 'spans'
    /** Noun for user-visible copy, e.g. "log" / "span". */
    recordNoun: string
    recordNounPlural: string
    /** Generated client for the product's `retention_rules` route. */
    api: {
        list: (projectId: string) => Promise<{ results: LogsRetentionRuleApi[] }>
        create: (projectId: string, body: CreateBody) => Promise<LogsRetentionRuleApi>
        retrieve: (projectId: string, id: string) => Promise<LogsRetentionRuleApi>
        destroy: (projectId: string, id: string) => Promise<void>
        partialUpdate: (projectId: string, id: string, body: PartialUpdateBody) => Promise<LogsRetentionRuleApi>
        reorder: (projectId: string, body: ReorderBody) => Promise<unknown>
        suggestName: (projectId: string, body: SuggestNameBody) => Promise<{ name?: string } | null>
    }
    /** Property vocabulary the rule's filter editor offers. */
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    urls: {
        newRule: () => string
        ruleDetail: (id: string) => string
        /** Settings page the rules table lives on — where saving a rule returns to. */
        settings: () => string
    }
    /**
     * Whether the rule form shows the ingested-volume preview and its storage projection.
     * Logs-only: the preview reads the logs bytes-volume endpoint, which traces has no
     * equivalent of yet.
     */
    showVolumePreview: boolean
}

export const LOGS_RETENTION_PRODUCT: RetentionRulesProduct = {
    source: 'logs',
    recordNoun: 'log',
    recordNounPlural: 'logs',
    api: {
        list: (projectId) => logsRetentionRulesList(projectId),
        create: (projectId, body) => logsRetentionRulesCreate(projectId, body),
        retrieve: (projectId, id) => logsRetentionRulesRetrieve(projectId, id),
        destroy: (projectId, id) => logsRetentionRulesDestroy(projectId, id),
        partialUpdate: (projectId, id, body) => logsRetentionRulesPartialUpdate(projectId, id, body),
        reorder: (projectId, body) => logsRetentionRulesReorderCreate(projectId, body),
        suggestName: (projectId, body) => logsRetentionRulesSuggestNameCreate(projectId, body),
    },
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.Logs,
        TaxonomicFilterGroupType.LogResourceAttributes,
        TaxonomicFilterGroupType.LogAttributes,
    ],
    urls: {
        newRule: () => urls.logsRetentionNew(),
        ruleDetail: (id) => urls.logsRetentionDetail(id),
        settings: () => logsRetentionRulesSettingsUrl(),
    },
    showVolumePreview: true,
}
