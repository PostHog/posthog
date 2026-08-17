import * as codeBubblePng from '@posthog/brand/hoggies/png/code-bubble'
import { IconEndpoints } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { EndpointPreview } from './EndpointPreview'
import { endpointsSetupLogic } from './endpointsSetupLogic'

const HedgehogCodeBubble = pngHoggie(codeBubblePng)

export const endpointsEmptyState: SceneProductEmptyState = {
    statusLogic: endpointsSetupLogic,
    config: {
        productKey: ProductKey.ENDPOINTS,
        productName: 'Endpoints',
        icon: <IconEndpoints />,
        accentColor: 'var(--color-product-endpoints-light)',
        accentColorDark: 'var(--color-product-endpoints-dark)',
        hedgehog: HedgehogCodeBubble,
        text: {
            'needs-setup': {
                headline: 'Turn a SQL query into an API endpoint',
                lead: 'Save a query as a named endpoint and call it from any application over the API. Update the query without changing your integration, and monitor every execution: bytes read, CPU usage, and duration. Materialize an endpoint to precompute its results and serve them fast.',
            },
        },
        primaryAction: { label: 'Create your first endpoint', to: urls.sqlEditor({ source: 'endpoint' }) },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/endpoints',
        previewLabel: 'Your endpoints, once created',
        Preview: EndpointPreview,
    },
}
