import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { ClientGenerator, type OpenApiSpec, type SearchDoc } from '../scripts/client-generator'
import { loadYamlDefinitions } from '../scripts/load-yaml'
import { SPECIAL_CLIENT_METHODS } from '../scripts/special-tools'
import { TINY_SCHEMAS_NAMESPACE_SOURCE } from './fixtures/tiny-schemas'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const FIXTURE_DIR = path.resolve(__dirname, 'fixtures')

function loadFixtureSpec(): OpenApiSpec {
    return JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, 'tiny-openapi.json'), 'utf-8')) as OpenApiSpec
}

describe('ClientGenerator (against tiny fixture spec)', () => {
    const spec = loadFixtureSpec()
    const knownSchemas = new Set(['Pet', 'PetTag', 'PaginatedPetList'])
    const gen = new ClientGenerator(spec, {}, knownSchemas)
    const ops = gen.collectOperations()

    it('collects every operation from the spec', () => {
        const names = ops.map((o) => o.methodName).sort()
        expect(names).toEqual(['petsCreate', 'petsList', 'petsRetrieve'])
    })

    it('renders a Client class with one method per operation', () => {
        const ts = gen.renderClientTs(ops)
        expect(ts).toContain('export class Client')
        expect(ts).toContain('async petsList(')
        expect(ts).toContain('async petsCreate(')
        expect(ts).toContain('async petsRetrieve(')
        expect(ts).toContain('Promise<Schemas.PaginatedPetList>')
        expect(ts).toContain('Promise<Schemas.Pet>')
        // Path params are resolved into local consts before URL interpolation.
        expect(ts).toContain('const id = input!.path!.id')
        expect(ts).toContain('${encodeURIComponent(String(id))}')
    })

    it('renders sdk.d.ts with Schemas namespace and Client interface', () => {
        const dts = gen.renderSdkDts(ops, TINY_SCHEMAS_NAMESPACE_SOURCE)
        expect(dts).toContain('export namespace Schemas')
        expect(dts).toContain('export interface Client')
        expect(dts).toContain('petsList(')
    })

    it('auto-resolves project_id and organization_id from context', () => {
        const projectScopedSpec: OpenApiSpec = {
            paths: {
                '/api/projects/{project_id}/widgets/': {
                    get: {
                        operationId: 'widgets_list',
                        parameters: [{ in: 'path', name: 'project_id', required: true, schema: { type: 'string' } }],
                        responses: { '200': { description: 'OK' } },
                    },
                },
                '/api/organizations/{organization_id}/things/': {
                    get: {
                        operationId: 'things_list',
                        parameters: [
                            { in: 'path', name: 'organization_id', required: true, schema: { type: 'string' } },
                        ],
                        responses: { '200': { description: 'OK' } },
                    },
                },
            },
        }
        const localGen = new ClientGenerator(projectScopedSpec, {}, new Set())
        const localOps = localGen.collectOperations()
        const ts = localGen.renderClientTs(localOps)
        expect(ts).toContain('const project_id = input?.path?.project_id ?? (await this.context.getProjectId())')
        expect(ts).toContain(
            'const organization_id = input?.path?.organization_id ?? (await this.context.getOrganizationId())'
        )
        expect(ts).toContain('private context: Context')

        const dts = localGen.renderSdkDts(localOps, '')
        // Optional path because all params are auto-resolved
        expect(dts).toContain('path?: {')
        // Method input is fully optional too (no body, no required query)
        expect(dts).toContain('widgetsList(input?:')
    })

    it('builds search docs for both operations and types', () => {
        const docs: SearchDoc[] = gen.buildSearchDocs(ops, TINY_SCHEMAS_NAMESPACE_SOURCE)
        const opDocs = docs.filter((d) => d.kind === 'operation').map((d) => d.name)
        const typeDocs = docs.filter((d) => d.kind === 'type').map((d) => d.name)
        expect(opDocs.sort()).toEqual(['petsCreate', 'petsList', 'petsRetrieve'])
        expect(typeDocs).toContain('Pet')
        expect(typeDocs).toContain('PetTag')
        expect(typeDocs).toContain('PaginatedPetList')
    })
})

describe('ClientGenerator with YAML gating', () => {
    const spec = loadFixtureSpec()
    const knownSchemas = new Set(['Pet', 'PetTag', 'PaginatedPetList'])
    const yamlIndex = loadYamlDefinitions(path.resolve(FIXTURE_DIR, 'tiny-yaml'))
    const gen = new ClientGenerator(spec, {}, knownSchemas, { yamlIndex })
    const ops = gen.collectOperations()

    it('emits only YAML-enabled operations', () => {
        const names = ops.map((o) => o.methodName).sort()
        expect(names).toEqual(['petsList', 'petsRetrieve'])
        expect(names).not.toContain('petsCreate')
    })

    it('uses YAML descriptions over OpenAPI descriptions when present', () => {
        const petsList = ops.find((o) => o.methodName === 'petsList')
        expect(petsList?.description).toBe('Curated description from YAML.')
    })

    it('emits query wrapper methods on the Client', () => {
        const ts = gen.renderClientTs(ops)
        expect(ts).toContain('async queryTiny(')
        expect(ts).toContain('this.runQuery(input.query)')
        const dts = gen.renderSdkDts(ops, TINY_SCHEMAS_NAMESPACE_SOURCE)
        expect(dts).toContain('queryTiny(')
        expect(dts).toContain('A tiny query wrapper used in tests.')
        expect(dts).toContain('When to use: Tiny test wrapper')
    })

    it('includes wrapper docs in the search index', () => {
        const docs = gen.buildSearchDocs(ops, TINY_SCHEMAS_NAMESPACE_SOURCE)
        const wrapper = docs.find((d) => d.name === 'queryTiny')
        expect(wrapper).not.toBeUndefined()
        expect(wrapper?.description).toContain('A tiny query wrapper used in tests.')
    })
})

describe('ClientGenerator with special methods', () => {
    const spec = loadFixtureSpec()
    const knownSchemas = new Set(['Pet', 'PetTag', 'PaginatedPetList'])
    const gen = new ClientGenerator(spec, {}, knownSchemas, { specialMethods: SPECIAL_CLIENT_METHODS })
    const ops = gen.collectOperations()

    it('emits executeSql / readDataSchema / readDataWarehouseSchema in client.ts', () => {
        const ts = gen.renderClientTs(ops)
        expect(ts).toContain('async executeSql(input: ExecuteSqlInput)')
        expect(ts).toContain('async readDataSchema(input: ReadDataSchemaInput)')
        expect(ts).toContain('async readDataWarehouseSchema()')
        expect(ts).toContain("this.invokeMcpTool<string>('execute_sql'")
        expect(ts).toContain('private async invokeMcpTool')
        expect(ts).toContain('/api/environments/${encodeURIComponent(project_id)}/mcp_tools/')
    })

    it('emits the same in sdk.d.ts including input interfaces', () => {
        const dts = gen.renderSdkDts(ops, TINY_SCHEMAS_NAMESPACE_SOURCE)
        expect(dts).toContain('export interface ExecuteSqlInput')
        expect(dts).toContain('executeSql(input: ExecuteSqlInput): Promise<string>')
        expect(dts).toContain('readDataWarehouseSchema(): Promise<string>')
    })

    it('includes special methods in the search index', () => {
        const docs = gen.buildSearchDocs(ops, TINY_SCHEMAS_NAMESPACE_SOURCE)
        const sql = docs.find((d) => d.name === 'executeSql')
        expect(sql).not.toBeUndefined()
        expect(sql?.summary).toBe('Execute a HogQL SQL query')
    })
})
