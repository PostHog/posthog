import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { discoverDefinitions } from '../../scripts/lib/definitions.mjs'

function withTempDirs(run: (paths: { rootDir: string; definitionsDir: string; productsDir: string }) => void): void {
    const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-definitions-'))
    const definitionsDir = path.join(rootDir, 'services', 'mcp', 'definitions')
    const productsDir = path.join(rootDir, 'products')
    fs.mkdirSync(definitionsDir, { recursive: true })
    fs.mkdirSync(productsDir, { recursive: true })

    try {
        run({ rootDir, definitionsDir, productsDir })
    } finally {
        fs.rmSync(rootDir, { recursive: true, force: true })
    }
}

describe('discoverDefinitions', () => {
    it.each(['tools.yaml', 'tools.yml'])('accepts products/<product>/mcp/%s', (fileName) => {
        withTempDirs(({ definitionsDir, productsDir }) => {
            const productMcpDir = path.join(productsDir, 'actions', 'mcp')
            fs.mkdirSync(productMcpDir, { recursive: true })
            fs.writeFileSync(path.join(productMcpDir, fileName), 'tools: {}\n')

            const result = discoverDefinitions({ definitionsDir, productsDir })

            expect(result).toEqual([
                {
                    moduleName: 'actions',
                    filePath: path.join(productMcpDir, fileName),
                },
            ])
        })
    })

    it('rejects products/<product>/mcp/*.yaml names other than tools.yaml', () => {
        withTempDirs(({ definitionsDir, productsDir }) => {
            const productMcpDir = path.join(productsDir, 'llm_analytics', 'mcp')
            fs.mkdirSync(productMcpDir, { recursive: true })
            fs.writeFileSync(path.join(productMcpDir, 'prompts.yaml'), 'tools: {}\n')

            expect(() => discoverDefinitions({ definitionsDir, productsDir })).toThrow(
                'expected "tools.yaml or tools.yml", found "prompts.yaml"'
            )
        })
    })

    it('rejects multiple YAML files in products/<product>/mcp', () => {
        withTempDirs(({ definitionsDir, productsDir }) => {
            const productMcpDir = path.join(productsDir, 'actions', 'mcp')
            fs.mkdirSync(productMcpDir, { recursive: true })
            fs.writeFileSync(path.join(productMcpDir, 'tools.yaml'), 'tools: {}\n')
            fs.writeFileSync(path.join(productMcpDir, 'extra.yaml'), 'tools: {}\n')

            expect(() => discoverDefinitions({ definitionsDir, productsDir })).toThrow(
                'expected exactly one YAML file named "tools.yaml or tools.yml"'
            )
        })
    })

    it('keeps services/mcp/definitions extension-flexible', () => {
        withTempDirs(({ definitionsDir, productsDir }) => {
            fs.writeFileSync(path.join(definitionsDir, 'base.yaml'), 'tools: {}\n')
            fs.writeFileSync(path.join(definitionsDir, 'legacy.yml'), 'tools: {}\n')

            const result = discoverDefinitions({ definitionsDir, productsDir })
            const moduleNames = result.map((item) => item.moduleName)

            expect(moduleNames).toContain('base')
            expect(moduleNames).toContain('legacy')
        })
    })
})
