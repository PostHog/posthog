import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import type { ProviderSpec } from './schema'

export const hubspot: ProviderSpec = {
    kind: 'hubspot',
    label: 'HubSpot',
    authTypes: { default: 'oauth', others: [] },
    authorize: {
        url: 'https://app.hubspot.com/oauth/authorize',
        scope: [
            'tickets',
            'crm.objects.contacts.write',
            'sales-email-read',
            'crm.objects.companies.read',
            'crm.objects.deals.read',
            'crm.objects.contacts.read',
            'crm.objects.quotes.read',
            'crm.objects.companies.write',
        ].join(' '),
        // Only some HubSpot plans have these objects. A required scope that a portal lacks fails the
        // whole authorization, so they stay optional and their warehouse tables start deselected.
        extraParams: [
            [
                'optional_scope',
                [
                    'analytics.behavioral_events.send',
                    'behavioral_events.event_definitions.read_write',
                    'crm.objects.leads.read',
                    'crm.objects.owners.read',
                    'crm.objects.line_items.read',
                    'crm.objects.products.read',
                    'crm.objects.invoices.read',
                    'crm.objects.orders.read',
                    'crm.objects.subscriptions.read',
                    'crm.objects.commercepayments.read',
                    'crm.objects.forecasts.read',
                    'conversations.read',
                ].join(' '),
            ],
        ],
        pkce: false,
        opaqueState: false,
    },
    token: { url: 'https://api.hubapi.com/oauth/v1/token', auth: 'client_secret_post' },
    clientSecretKeys: {
        clientId: '__PROVIDER_HUBSPOT_APP_CLIENT_ID',
        clientSecret: '__PROVIDER_HUBSPOT_APP_CLIENT_SECRET',
    },
    identityConfigKeys: ['hub_id', 'hub_domain', 'user', 'user_id'],
    tokenInfo: {
        idPath: 'hub_id',
        namePath: 'hub_domain',
        request: {
            url: 'https://api.hubapi.com/oauth/v1/access-tokens/:access_token',
            configFields: ['hub_id', 'hub_domain', 'user', 'user_id', 'scopes'],
        },
    },
    refresh: {
        ...OAUTH_REFRESH,
        mode: 'static',
        // A grant whose portal was deleted or disconnected. HubSpot sends no `invalid_grant` code for it.
        terminalErrors: [{ path: 'status', equals: 'BAD_HUB', statusBelow: 500 }],
    },
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: ['hub_domain'] },
}
