import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { SubscriptionInsightCriteriaEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

export function InsightCriteriaField(): JSX.Element {
    return (
        <LemonField
            name={['delivery_config', 'insight_criteria']}
            help="Checked each time the subscription sends. Insights whose results are empty or all zero are left out, and if none have data the delivery is skipped."
        >
            {({ value, onChange }) => (
                <LemonSwitch
                    bordered
                    fullWidth
                    checked={value === SubscriptionInsightCriteriaEnumApi.HasData}
                    // Omitted rather than null: the API treats an absent key as "send every insight".
                    onChange={(checked) => onChange(checked ? SubscriptionInsightCriteriaEnumApi.HasData : undefined)}
                    label="Only send insights that have data"
                    data-attr="subscription-insight-criteria-has-data"
                />
            )}
        </LemonField>
    )
}
