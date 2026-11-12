import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { HOOK_SOURCE_HASHES } from '@/cli/catalog/hook-versions'
import { GENERATED_TOOL_HOOKS } from '@/tools/generated/hooks'

function sourceHash(name: string): string {
    const source = readFileSync(resolve(__dirname, '../../src/tools', `${name}.ts`))
    return createHash('sha256').update(source).digest('hex').slice(0, 12)
}

describe('CLI catalog hook versions', () => {
    it('versions every compiled-in hook', () => {
        expect(Object.keys(HOOK_SOURCE_HASHES).sort()).toEqual(Object.keys(GENERATED_TOOL_HOOKS).sort())
    })

    it.each(Object.keys(GENERATED_TOOL_HOOKS))('gives %s a new version when its source changes', (name) => {
        const hashes = HOOK_SOURCE_HASHES[name] ?? []

        expect(
            hashes.at(-1),
            `Append '${sourceHash(name)}' to ${name} in src/cli/catalog/hook-versions.ts, which makes it version ${hashes.length + 1}`
        ).toBe(sourceHash(name))
    })
})
