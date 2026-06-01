import { describe, expect, it } from 'vitest'

import { generateCliManifest, type CategoryBundle } from '../../scripts/generate-cli-manifest'
import type { JsonSchemaRoot } from '../../scripts/lib/json-schema-to-zod'
import type { EnabledToolConfig } from '../../scripts/yaml-config-schema'

const baseToolConfig: EnabledToolConfig = {
    operation: 'things_create',
    enabled: true,
    scopes: ['thing:write'],
    annotations: { readOnly: false, destructive: false, idempotent: false },
}

const helpers: Parameters<typeof generateCliManifest>[2] = {
    composeToolSchema: () => ({
        pathParamNames: [],
        queryParamNames: [],
        bodyFieldNames: [],
        renamedFields: {},
        paramFallbacks: {},
    }),
    resolveDescription: (_config, _yamlDir, fallback) => fallback,
    extractKindFromSchemaRef: () => 'TrendsQuery',
    bodyMeta: () => ({}),
}

function manifestForCategory(category: string): ReturnType<typeof generateCliManifest> {
    const bundle: CategoryBundle = {
        config: { feature: 'things', category },
        enabledTools: [
            [
                'things-create',
                baseToolConfig,
                {
                    method: 'POST',
                    path: '/api/projects/{project_id}/things/',
                    operation: {
                        parameters: [],
                        summary: 'Create a thing',
                    },
                },
            ],
        ],
        enabledWrappers: [],
        yamlDir: '',
    }

    return generateCliManifest([bundle], { definitions: {} } as JsonSchemaRoot, helpers)
}

describe('generateCliManifest', () => {
    it('keeps analytics category slugs intact', () => {
        const manifest = manifestForCategory('Product analytics')

        expect(manifest['things-create']?.category).toBe('product-analytics')
    })

    it('singularizes ordinary plural category slugs', () => {
        const manifest = manifestForCategory('Feature flags')

        expect(manifest['things-create']?.category).toBe('feature-flag')
    })
})
