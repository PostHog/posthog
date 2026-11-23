import { BindLogic } from 'kea'

import { Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { LogsRetentionRulesSortableTable } from './LogsRetentionRulesSortableTable'
import { logsRetentionSectionLogic } from './logsRetentionSectionLogic'
import { LOGS_RETENTION_PRODUCT, RetentionRulesProduct } from './retentionRulesProduct'

/** The rules table plus its explanation. Traces pass their own product; logs is the default. */
export function RetentionRulesSection({ product }: { product: RetentionRulesProduct }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <BindLogic logic={logsRetentionSectionLogic} props={{ product }}>
                <div className="flex flex-col gap-3">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Keep some {product.recordNounPlural} longer or shorter than the environment default. Rules run
                        top to bottom during ingestion. Drag the handle on each row to change that order. The first
                        matching rule sets a {product.recordNoun}'s retention, and {product.recordNounPlural} that match
                        no rule keep the environment default. Retention is applied at ingest, so a change only has an
                        effect on {product.recordNounPlural} received after it.
                    </Text>
                    <LogsRetentionRulesSortableTable />
                </div>
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={logsRetentionSectionLogic} props={{ product }}>
            <div className="space-y-3">
                <p className="text-muted m-0">
                    Keep some {product.recordNounPlural} longer or shorter than the environment default. Rules run top
                    to bottom during ingestion. Drag the handle on each row to change that order. The first matching
                    rule sets a {product.recordNoun}'s retention, and {product.recordNounPlural} that match no rule keep
                    the environment default. Retention is applied at ingest, so a change only has an effect on{' '}
                    {product.recordNounPlural} received after it.
                </p>
                <LogsRetentionRulesSortableTable />
            </div>
        </BindLogic>
    )
}

export function LogsRetentionSection(): JSX.Element | null {
    const enabled = useFeatureFlag(LogsFeatureFlagKeys.retentionRules)
    if (!enabled) {
        return null
    }
    return <RetentionRulesSection product={LOGS_RETENTION_PRODUCT} />
}
