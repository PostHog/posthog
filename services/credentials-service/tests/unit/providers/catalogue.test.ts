import { build } from 'esbuild'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { PROVIDER_SPECS } from '@/providers'
import { buildCatalogue } from '@/providers/catalogue'

const GENERATED = fileURLToPath(
    new URL('../../../../../posthog/integrations/catalogue_generated.json', import.meta.url)
)
const ENTRY = fileURLToPath(new URL('../../../src/catalogue.ts', import.meta.url))

describe('catalogue', () => {
    it('matches the checked-in catalogue_generated.json', () => {
        const checkedIn: unknown = JSON.parse(readFileSync(GENERATED, 'utf8'))
        // On a failure, run `hogli build:projections --only credentials-catalogue` and commit the result.
        expect(checkedIn).toEqual(buildCatalogue(PROVIDER_SPECS))
    })

    // The projection check runs in a CI job with no node_modules, so the entry must bundle on its own.
    it('bundles without any npm package', async () => {
        const result = await build({
            entryPoints: [ENTRY],
            bundle: true,
            platform: 'node',
            format: 'esm',
            write: false,
            metafile: true,
            packages: 'external',
            logLevel: 'silent',
        })
        const imports = Object.values(result.metafile.outputs).flatMap((output) => output.imports.map((i) => i.path))
        expect(imports.filter((path) => !path.startsWith('node:'))).toEqual([])
    })

    it('lists the authorize template that Django fills, with the client id by name only', () => {
        const hubspot = buildCatalogue(PROVIDER_SPECS).kinds['hubspot']
        expect(hubspot?.authorize?.params.slice(0, 5)).toEqual([
            ['client_id', '{client_id}'],
            ['scope', hubspot?.authorize?.scope],
            ['redirect_uri', '{redirect_uri}'],
            ['response_type', 'code'],
            ['state', '{state}'],
        ])
        expect(hubspot?.authorize?.client_id_key).toBe('HUBSPOT_APP_CLIENT_ID')
        expect(JSON.stringify(buildCatalogue(PROVIDER_SPECS))).not.toMatch(/CLIENT_SECRET|clientSecret|private_?key/i)
    })
})
