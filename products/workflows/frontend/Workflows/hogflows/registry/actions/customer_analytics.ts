import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    nodes: [
        {
            type: 'function',
            name: 'Get account',
            description: 'Fetch a Customer analytics account into a workflow variable.',
            config: { template_id: 'template-posthog-get-account', inputs: {} },
            // The account response nests role contacts (csm/account_executive/account_owner) as
            // {id, email}, so a flat `spread` can't reach them. Map each field explicitly via
            // result_path instead, while keeping the whole object available under `account`.
            output_variable: [
                { key: 'account', result_path: null, label: 'Account' },
                { key: 'account_csm_email', result_path: 'properties.csm.email', label: 'CSM email' },
                { key: 'account_csm_id', result_path: 'properties.csm.id', label: 'CSM ID' },
                {
                    key: 'account_executive_email',
                    result_path: 'properties.account_executive.email',
                    label: 'Account executive email',
                },
                {
                    key: 'account_executive_id',
                    result_path: 'properties.account_executive.id',
                    label: 'Account executive ID',
                },
                {
                    key: 'account_owner_email',
                    result_path: 'properties.account_owner.email',
                    label: 'Account owner email',
                },
                { key: 'account_owner_id', result_path: 'properties.account_owner.id', label: 'Account owner ID' },
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
            output_variable: { key: 'account', result_path: null },
        },
    ],
})
