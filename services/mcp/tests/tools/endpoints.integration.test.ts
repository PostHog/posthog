import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    API_BASE_URL,
    API_TOKEN,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import createEndpointTool from '@/tools/endpoints/create'
import deleteEndpointTool from '@/tools/endpoints/delete'
import getEndpointTool from '@/tools/endpoints/get'
import getAllEndpointsTool from '@/tools/endpoints/getAll'
import runEndpointTool from '@/tools/endpoints/run'
import updateEndpointTool from '@/tools/endpoints/update'
import getEndpointVersionsTool from '@/tools/endpoints/versions'
import createInsightVariableTool from '@/tools/insightVariables/create'
import getAllInsightVariablesTool from '@/tools/insightVariables/getAll'
import type { Context } from '@/tools/types'

// Helper to delete insight variables via raw API (no MCP delete tool exists)
async function deleteInsightVariable(variableId: string): Promise<void> {
    await fetch(`${API_BASE_URL}/api/environments/${TEST_PROJECT_ID}/insight_variables/${variableId}/`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${API_TOKEN}` },
    })
}

describe('Endpoints', { concurrent: false }, () => {
    let context: Context
    const createdEndpointNames: string[] = []
    const createdVariableIds: string[] = []

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const name of createdEndpointNames) {
            try {
                await context.api.endpoints({ projectId: TEST_PROJECT_ID! }).delete({ name })
            } catch {
                // ignore cleanup errors
            }
        }
        createdEndpointNames.length = 0

        for (const id of createdVariableIds) {
            try {
                await deleteInsightVariable(id)
            } catch {
                // ignore cleanup errors
            }
        }
        createdVariableIds.length = 0
    })

    // ── Basic CRUD ──────────────────────────────────────────────────

    describe('endpoint-create tool', () => {
        const createTool = createEndpointTool()

        it('should create an endpoint with a HogQL query', async () => {
            const name = generateUniqueKey('test-ep')

            const result = await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                    description: 'Integration test endpoint',
                },
            })

            const data = parseToolResponse(result)
            createdEndpointNames.push(name)

            expect(data.name).toBe(name)
            expect(data.is_active).toBe(true)
            expect(data.current_version).toBe(1)
            expect(data.url).toContain('/pipeline/endpoints/')
        })

        it('should create an inactive endpoint', async () => {
            const name = generateUniqueKey('inactive-ep')

            const result = await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                    is_active: false,
                },
            })

            const data = parseToolResponse(result)
            createdEndpointNames.push(name)

            expect(data.is_active).toBe(false)
        })

        it('should create an endpoint with custom cache_age_seconds', async () => {
            const name = generateUniqueKey('cached-ep')

            const result = await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                    cache_age_seconds: 3600,
                },
            })

            const data = parseToolResponse(result)
            createdEndpointNames.push(name)

            expect(data.cache_age_seconds).toBe(3600)
        })
    })

    describe('endpoints-get-all tool', () => {
        const createTool = createEndpointTool()
        const getAllTool = getAllEndpointsTool()

        it('should list endpoints including a newly created one', async () => {
            const name = generateUniqueKey('list-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                },
            })
            createdEndpointNames.push(name)

            const result = await getAllTool.handler(context, {})

            const data = parseToolResponse(result)
            expect(Array.isArray(data)).toBe(true)
            expect(data.some((ep: any) => ep.name === name)).toBe(true)
        })

        it('should filter by active status', async () => {
            const activeName = generateUniqueKey('active-ep')
            const inactiveName = generateUniqueKey('inactive-ep')

            await createTool.handler(context, {
                data: { name: activeName, query: { kind: 'HogQLQuery', query: 'SELECT 1' }, is_active: true },
            })
            createdEndpointNames.push(activeName)

            await createTool.handler(context, {
                data: { name: inactiveName, query: { kind: 'HogQLQuery', query: 'SELECT 1' }, is_active: false },
            })
            createdEndpointNames.push(inactiveName)

            const result = await getAllTool.handler(context, { data: { is_active: true } })
            const data = parseToolResponse(result)

            expect(data.some((ep: any) => ep.name === activeName)).toBe(true)
            expect(data.some((ep: any) => ep.name === inactiveName)).toBe(false)
        })
    })

    describe('endpoint-get tool', () => {
        const createTool = createEndpointTool()
        const getTool = getEndpointTool()

        it('should get an endpoint by name', async () => {
            const name = generateUniqueKey('get-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                    description: 'Get test',
                },
            })
            createdEndpointNames.push(name)

            const result = await getTool.handler(context, { name })

            const data = parseToolResponse(result)
            expect(data.name).toBe(name)
            expect(data.description).toBe('Get test')
        })

        it('should get a specific version of an endpoint', async () => {
            const name = generateUniqueKey('getver-ep')
            const updateTool = updateEndpointTool()

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                    description: 'v1',
                },
            })
            createdEndpointNames.push(name)

            await updateTool.handler(context, {
                name,
                data: { query: { kind: 'HogQLQuery', query: 'SELECT 2' }, description: 'v2' },
            })

            const v1 = parseToolResponse(await getTool.handler(context, { name, version: 1 }))
            const v2 = parseToolResponse(await getTool.handler(context, { name, version: 2 }))

            expect(v1.description).toBe('v1')
            expect(v2.description).toBe('v2')
        })
    })

    describe('endpoint-update tool', () => {
        const createTool = createEndpointTool()
        const updateTool = updateEndpointTool()

        it('should update description without bumping version', async () => {
            const name = generateUniqueKey('upd-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                },
            })
            createdEndpointNames.push(name)

            const result = await updateTool.handler(context, {
                name,
                data: { description: 'Updated description' },
            })

            const data = parseToolResponse(result)
            expect(data.name).toBe(name)
            expect(data.description).toBe('Updated description')
            expect(data.current_version).toBe(1)
        })

        it('should create a new version when query changes', async () => {
            const name = generateUniqueKey('ver-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                },
            })
            createdEndpointNames.push(name)

            const result = await updateTool.handler(context, {
                name,
                data: { query: { kind: 'HogQLQuery', query: 'SELECT 2' } },
            })

            const data = parseToolResponse(result)
            expect(data.current_version).toBe(2)
        })

        it('should toggle is_active', async () => {
            const name = generateUniqueKey('toggle-ep')

            await createTool.handler(context, {
                data: { name, query: { kind: 'HogQLQuery', query: 'SELECT 1' } },
            })
            createdEndpointNames.push(name)

            const deactivated = parseToolResponse(
                await updateTool.handler(context, { name, data: { is_active: false } })
            )
            expect(deactivated.is_active).toBe(false)

            const reactivated = parseToolResponse(
                await updateTool.handler(context, { name, data: { is_active: true } })
            )
            expect(reactivated.is_active).toBe(true)
        })
    })

    describe('endpoint-delete tool', () => {
        const createTool = createEndpointTool()
        const deleteTool = deleteEndpointTool()

        it('should delete an endpoint', async () => {
            const name = generateUniqueKey('del-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                },
            })

            const result = await deleteTool.handler(context, { name })

            const data = parseToolResponse(result)
            expect(data.success).toBe(true)
        })

        it('should fail when deleting a non-existent endpoint', async () => {
            const deleteTool = deleteEndpointTool()

            await expect(deleteTool.handler(context, { name: 'does-not-exist-ever' })).rejects.toThrow()
        })
    })

    describe('endpoint-run tool', () => {
        const createTool = createEndpointTool()
        const runTool = runEndpointTool()

        it('should execute a simple HogQL endpoint', async () => {
            const name = generateUniqueKey('run-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT 1 AS value' },
                },
            })
            createdEndpointNames.push(name)

            const result = await runTool.handler(context, { name })

            const data = parseToolResponse(result)
            expect(data).toBeTruthy()
        })

        it('should execute with limit and offset', async () => {
            const name = generateUniqueKey('paged-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: {
                        kind: 'HogQLQuery',
                        query: 'SELECT number AS n FROM numbers(10)',
                    },
                },
            })
            createdEndpointNames.push(name)

            const result = await runTool.handler(context, {
                name,
                data: { limit: 3, offset: 0 },
            })

            const data = parseToolResponse(result)
            expect(data).toBeTruthy()
        })

        it('should execute with force refresh', async () => {
            const name = generateUniqueKey('force-ep')

            await createTool.handler(context, {
                data: {
                    name,
                    query: { kind: 'HogQLQuery', query: 'SELECT now() AS ts' },
                },
            })
            createdEndpointNames.push(name)

            const result = await runTool.handler(context, {
                name,
                data: { refresh: 'force' },
            })

            const data = parseToolResponse(result)
            expect(data).toBeTruthy()
        })
    })

    describe('endpoint-versions tool', () => {
        const createTool = createEndpointTool()
        const updateTool = updateEndpointTool()
        const versionsTool = getEndpointVersionsTool()

        it('should return single version for new endpoint', async () => {
            const name = generateUniqueKey('singlever-ep')

            await createTool.handler(context, {
                data: { name, query: { kind: 'HogQLQuery', query: 'SELECT 1' } },
            })
            createdEndpointNames.push(name)

            const result = await versionsTool.handler(context, { name })
            const data = parseToolResponse(result)

            expect(Array.isArray(data)).toBe(true)
            expect(data.length).toBe(1)
            expect(data[0].version).toBe(1)
        })

        it('should list version history after query updates', async () => {
            const name = generateUniqueKey('vers-ep')

            await createTool.handler(context, {
                data: { name, query: { kind: 'HogQLQuery', query: 'SELECT 1' } },
            })
            createdEndpointNames.push(name)

            await updateTool.handler(context, {
                name,
                data: { query: { kind: 'HogQLQuery', query: 'SELECT 2' } },
            })

            await updateTool.handler(context, {
                name,
                data: { query: { kind: 'HogQLQuery', query: 'SELECT 3' } },
            })

            const result = await versionsTool.handler(context, { name })
            const data = parseToolResponse(result)

            expect(Array.isArray(data)).toBe(true)
            expect(data.length).toBe(3)
        })
    })

    // ── Insight Variables ───────────────────────────────────────────

    describe('insight-variable tools', () => {
        const createVarTool = createInsightVariableTool()
        const getAllVarsTool = getAllInsightVariablesTool()

        it('should create an insight variable', async () => {
            const result = await createVarTool.handler(context, {
                data: { name: `Test Var ${Date.now()}`, type: 'String' },
            })

            const data = parseToolResponse(result)
            createdVariableIds.push(data.id)

            expect(data.id).toBeTruthy()
            expect(data.type).toBe('String')
            expect(data.code_name).toBeTruthy()
        })

        it('should create a variable with default value', async () => {
            const result = await createVarTool.handler(context, {
                data: {
                    name: `Default Var ${Date.now()}`,
                    type: 'Number',
                    default_value: 42,
                },
            })

            const data = parseToolResponse(result)
            createdVariableIds.push(data.id)

            expect(data.type).toBe('Number')
        })

        it.each([
            { type: 'String' as const },
            { type: 'Number' as const },
            { type: 'Boolean' as const },
            { type: 'List' as const },
            { type: 'Date' as const },
        ])('should create a variable of type $type', async ({ type }) => {
            const result = await createVarTool.handler(context, {
                data: { name: `Typed Var ${type} ${Date.now()}`, type },
            })

            const data = parseToolResponse(result)
            createdVariableIds.push(data.id)

            expect(data.type).toBe(type)
        })

        it('should list insight variables including newly created ones', async () => {
            const varResult = await createVarTool.handler(context, {
                data: { name: `List Var ${Date.now()}`, type: 'String' },
            })
            const varData = parseToolResponse(varResult)
            createdVariableIds.push(varData.id)

            const result = await getAllVarsTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(Array.isArray(data)).toBe(true)
            expect(data.some((v: any) => v.id === varData.id)).toBe(true)
        })
    })

    // ── Endpoints with Variables ────────────────────────────────────

    describe('endpoints with HogQL variables', () => {
        const createTool = createEndpointTool()
        const runTool = runEndpointTool()
        const createVarTool = createInsightVariableTool()

        it('should create and run an endpoint that uses a variable', async () => {
            // Step 1: Create an insight variable
            const varResult = await createVarTool.handler(context, {
                data: { name: `Limit Var ${Date.now()}`, type: 'Number', default_value: 5 },
            })
            const varData = parseToolResponse(varResult)
            createdVariableIds.push(varData.id)

            const codeName = varData.code_name

            // Step 2: Create an endpoint that references the variable
            const name = generateUniqueKey('var-ep')
            const createResult = await createTool.handler(context, {
                data: {
                    name,
                    query: {
                        kind: 'HogQLQuery',
                        query: `SELECT number AS n FROM numbers({variables.${codeName}})`,
                    },
                    description: 'Endpoint with variable',
                },
            })
            createdEndpointNames.push(name)
            const epData = parseToolResponse(createResult)
            expect(epData.name).toBe(name)

            // Step 3: Run the endpoint (uses default_value)
            const runResult = await runTool.handler(context, { name })
            const runData = parseToolResponse(runResult)
            expect(runData).toBeTruthy()
        })

        it('should run an endpoint with variable override', async () => {
            const varResult = await createVarTool.handler(context, {
                data: { name: `Override Var ${Date.now()}`, type: 'Number', default_value: 3 },
            })
            const varData = parseToolResponse(varResult)
            createdVariableIds.push(varData.id)

            const codeName = varData.code_name

            const name = generateUniqueKey('override-ep')
            await createTool.handler(context, {
                data: {
                    name,
                    query: {
                        kind: 'HogQLQuery',
                        query: `SELECT number AS n FROM numbers({variables.${codeName}})`,
                    },
                },
            })
            createdEndpointNames.push(name)

            // Override the variable value at runtime
            const runResult = await runTool.handler(context, {
                name,
                data: { variables: { [codeName]: 7 } },
            })

            const runData = parseToolResponse(runResult)
            expect(runData).toBeTruthy()
        })

        it('should fail to create an endpoint referencing an undefined variable', async () => {
            const name = generateUniqueKey('bad-var-ep')

            await expect(
                createTool.handler(context, {
                    data: {
                        name,
                        query: {
                            kind: 'HogQLQuery',
                            query: 'SELECT {variables.this_does_not_exist}',
                        },
                    },
                })
            ).rejects.toThrow(/undefined variable/i)
        })

        it('should create endpoint with string variable in WHERE clause', async () => {
            const varResult = await createVarTool.handler(context, {
                data: { name: `Filter Var ${Date.now()}`, type: 'String', default_value: 'test' },
            })
            const varData = parseToolResponse(varResult)
            createdVariableIds.push(varData.id)

            const codeName = varData.code_name

            const name = generateUniqueKey('where-ep')
            const result = await createTool.handler(context, {
                data: {
                    name,
                    query: {
                        kind: 'HogQLQuery',
                        query: `SELECT 1 AS value WHERE 'test' = {variables.${codeName}}`,
                    },
                },
            })
            createdEndpointNames.push(name)

            const data = parseToolResponse(result)
            expect(data.name).toBe(name)

            // Run it to verify the query compiles and executes
            const runResult = await runTool.handler(context, { name })
            expect(parseToolResponse(runResult)).toBeTruthy()
        })
    })

    // ── Full Lifecycle ──────────────────────────────────────────────

    describe('full endpoint lifecycle with variables', () => {
        const createTool = createEndpointTool()
        const getTool = getEndpointTool()
        const updateTool = updateEndpointTool()
        const runTool = runEndpointTool()
        const versionsTool = getEndpointVersionsTool()
        const deleteTool = deleteEndpointTool()
        const createVarTool = createInsightVariableTool()

        it('should handle create → run → update query → run → check versions → delete', async () => {
            // Create a variable for the endpoint
            const varResult = await createVarTool.handler(context, {
                data: { name: `Lifecycle Var ${Date.now()}`, type: 'Number', default_value: 3 },
            })
            const varData = parseToolResponse(varResult)
            createdVariableIds.push(varData.id)
            const codeName = varData.code_name

            // Create endpoint
            const name = generateUniqueKey('lifecycle-ep')
            await createTool.handler(context, {
                data: {
                    name,
                    query: {
                        kind: 'HogQLQuery',
                        query: `SELECT number AS n FROM numbers({variables.${codeName}})`,
                    },
                    description: 'v1: small numbers',
                },
            })
            // Don't push to cleanup — we'll delete manually at the end

            // Get and verify
            const getResult = parseToolResponse(await getTool.handler(context, { name }))
            expect(getResult.current_version).toBe(1)
            expect(getResult.description).toBe('v1: small numbers')

            // Run v1
            const run1 = parseToolResponse(await runTool.handler(context, { name }))
            expect(run1).toBeTruthy()

            // Update query → new version
            const updated = parseToolResponse(
                await updateTool.handler(context, {
                    name,
                    data: {
                        query: {
                            kind: 'HogQLQuery',
                            query: `SELECT number * 10 AS n FROM numbers({variables.${codeName}})`,
                        },
                        description: 'v2: multiplied numbers',
                    },
                })
            )
            expect(updated.current_version).toBe(2)
            expect(updated.description).toBe('v2: multiplied numbers')

            // Run v2
            const run2 = parseToolResponse(await runTool.handler(context, { name }))
            expect(run2).toBeTruthy()

            // Check versions
            const versions = parseToolResponse(await versionsTool.handler(context, { name }))
            expect(versions.length).toBe(2)

            // Delete
            const deleteResult = parseToolResponse(await deleteTool.handler(context, { name }))
            expect(deleteResult.success).toBe(true)
        })
    })
})
