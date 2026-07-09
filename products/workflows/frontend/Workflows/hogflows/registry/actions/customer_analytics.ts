import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { GroupType, GroupTypeIndex } from '~/types'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'
import { CyclotronInputType } from 'products/workflows/frontend/Workflows/hogflows/steps/types'

export const buildAccountExternalIdInputs = (
    accountGroupTypeIndex: number | null | undefined,
    groupTypes: Map<GroupTypeIndex, GroupType>
): Record<string, CyclotronInputType> | undefined => {
    if (accountGroupTypeIndex === null || accountGroupTypeIndex === undefined) {
        return undefined
    }
    const groupType = groupTypes.get(accountGroupTypeIndex as GroupTypeIndex)?.group_type
    if (!groupType) {
        return undefined
    }
    // Backtick-quote the group type as an identifier. Bracket access (`groups["x"]`) compiles the index as a
    // separate global lookup and fails at runtime; backtick quoting escapes any name (delimiters, spaces, backticks
    // via doubling) without breaking out of the Hog expression.
    const quotedGroupType = groupType.replace(/`/g, '``')
    return { external_id: { value: `{groups.\`${quotedGroupType}\`.id}` } }
}

const getAccountExternalIdDefaultInputs = (): Record<string, CyclotronInputType> | undefined =>
    buildAccountExternalIdInputs(
        teamLogic.findMounted()?.values.currentTeam?.customer_analytics_config?.account_group_type_index,
        groupsModel.findMounted()?.values.groupTypes ?? new Map()
    )

registerActionNodeCategory({
    label: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    nodes: [
        {
            type: 'function',
            name: 'Get account',
            description: 'Fetch a Customer analytics account into a workflow variable.',
            config: { template_id: 'template-posthog-get-account', inputs: {} },
            getDefaultInputs: getAccountExternalIdDefaultInputs,
            output_variable: [
                { key: 'account', result_path: null, label: 'Account' },
                { key: 'account_relationships', result_path: 'relationships', label: 'Relationships' },
                {
                    key: 'account_stripe_customer_id',
                    result_path: 'properties.stripe_customer_id',
                    label: 'Stripe customer ID',
                },
                {
                    key: 'account_hubspot_deal_id',
                    result_path: 'properties.hubspot_deal_id',
                    label: 'HubSpot deal ID',
                },
                { key: 'account_billing_id', result_path: 'properties.billing_id', label: 'Billing ID' },
                { key: 'account_sfdc_id', result_path: 'properties.sfdc_id', label: 'Salesforce ID' },
                { key: 'account_zendesk_id', result_path: 'properties.zendesk_id', label: 'Zendesk ID' },
                {
                    key: 'account_slack_channel_id',
                    result_path: 'properties.slack_channel_id',
                    label: 'Slack channel ID',
                },
            ],
        },
        {
            type: 'function',
            name: 'Update account',
            description: 'Assign role contacts or tag a Customer analytics account.',
            config: { template_id: 'template-posthog-update-account', inputs: {} },
            getDefaultInputs: getAccountExternalIdDefaultInputs,
            output_variable: { key: 'account', result_path: null },
        },
        {
            type: 'function',
            name: 'Update account property',
            description: 'Set custom property values on a Customer analytics account.',
            config: { template_id: 'template-posthog-update-account-property', inputs: {} },
            getDefaultInputs: getAccountExternalIdDefaultInputs,
            output_variable: { key: 'account', result_path: null },
        },
    ],
})
