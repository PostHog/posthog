import { describe, expect, it } from 'vitest'

import { matchFastPath } from '@/tools/code-exec/fast-path'

const IMPORT = "import { client } from '@posthog/sdk'"

// The matcher is the fast path's safety boundary (spec §4.2): a false match
// dispatches a script that needed the sandbox; a false miss only costs the
// optimization. Every row below pins one qualification rule so neither an
// accidental widening (toward an interpreter) nor a narrowing regression can
// land silently.
describe('matchFastPath', () => {
    it.each([
        {
            case: 'a zero-argument awaited call',
            source: `${IMPORT}\nexport default await client.featureFlags.list()`,
            expected: { methodId: 'featureFlags.list', args: [] },
        },
        {
            case: 'a call without await',
            source: `${IMPORT}\nexport default client.featureFlags.list()`,
            expected: { methodId: 'featureFlags.list', args: [] },
        },
        {
            case: 'nested literal arguments incl. negative numbers, template literals, null, and string keys',
            source: `${IMPORT}\nexport default await client.featureFlags.update({ id: 1, active: false, name: \`alpha\`, tags: ['a', -2], meta: { note: null, 'quoted-key': true } })`,
            expected: {
                methodId: 'featureFlags.update',
                args: [
                    {
                        id: 1,
                        active: false,
                        name: 'alpha',
                        tags: ['a', -2],
                        meta: { note: null, 'quoted-key': true },
                    },
                ],
            },
        },
        {
            case: 'the two-statement const/export-default pair',
            source: `${IMPORT}\nconst flags = await client.featureFlags.list({ limit: 5 })\nexport default flags`,
            expected: { methodId: 'featureFlags.list', args: [{ limit: 5 }] },
        },
        {
            case: 'type-only imports and comments riding along',
            source: [
                '// list the flags',
                "import type { FeatureFlag } from '@posthog/sdk'",
                IMPORT,
                '/* block comment */',
                'export default await client.featureFlags.list()',
            ].join('\n'),
            expected: { methodId: 'featureFlags.list', args: [] },
        },
    ])('matches $case', async ({ source, expected }) => {
        await expect(matchFastPath(source)).resolves.toEqual(expected)
    })

    it.each([
        { case: 'an identifier argument', source: `${IMPORT}\nexport default await client.flags.update({ id: x })` },
        { case: 'a shorthand property', source: `${IMPORT}\nexport default await client.flags.update({ id })` },
        { case: 'a computed value', source: `${IMPORT}\nexport default await client.flags.list({ limit: 1 + 1 })` },
        { case: 'a ternary', source: `${IMPORT}\nexport default await client.flags.list({ limit: 1 ? 1 : 2 })` },
        {
            case: 'a template literal with a substitution',
            source: `${IMPORT}\nexport default await client.flags.update({ name: \`flag-\${1}\` })`,
        },
        { case: 'an object spread', source: `${IMPORT}\nexport default await client.flags.update({ ...base })` },
        { case: 'a computed key', source: `${IMPORT}\nexport default await client.flags.update({ ['id']: 1 })` },
        { case: 'a second argument', source: `${IMPORT}\nexport default await client.flags.list({}, { signal: s })` },
        {
            case: 'a chained call',
            source: `${IMPORT}\nexport default await client.flags.list().then((r) => r)`,
        },
        { case: 'a deeper property chain', source: `${IMPORT}\nexport default await client.a.b.c()` },
        { case: 'optional chaining', source: `${IMPORT}\nexport default await client.flags?.list()` },
        {
            case: 'an extra effectful statement',
            source: `${IMPORT}\nconsole.log('hi')\nexport default await client.flags.list()`,
        },
        {
            case: 'two SDK calls',
            source: `${IMPORT}\nconst a = await client.flags.list()\nexport default await client.flags.list()`,
        },
        {
            case: 'a const/export pair naming different identifiers',
            source: `${IMPORT}\nconst a = await client.flags.list()\nexport default b`,
        },
        {
            case: 'an aliased client import',
            source: `import { client as c } from '@posthog/sdk'\nexport default await c.flags.list()`,
        },
        {
            case: 'a default import',
            source: `import sdk from '@posthog/sdk'\nexport default await sdk.client.flags.list()`,
        },
        {
            case: 'an import from another module',
            source: `import { client } from 'other'\nexport default await client.flags.list()`,
        },
        { case: 'a missing client import', source: 'export default await client.flags.list()' },
        { case: 'a missing export default', source: `${IMPORT}\nconst x = await client.flags.list()` },
        { case: 'an export default without an SDK call', source: `${IMPORT}\nexport default 42` },
        { case: 'generic type arguments', source: `${IMPORT}\nexport default await client.query.run<number>({})` },
        { case: 'a syntax error', source: `${IMPORT}\nexport default await client.flags.list(` },
    ])('rejects $case', async ({ source }) => {
        await expect(matchFastPath(source)).resolves.toBeNull()
    })
})
