import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ConfigVersionApi } from '../generated/api.schemas'
import { aiEnrichmentLogic } from './aiEnrichmentLogic'

const CONFIG_V1: ConfigVersionApi = {
    id: 'config-v1',
    name: 'test_label',
    version: 'v1',
    prompt_text: 'original prompt',
    model: 'gpt-5-mini',
    input_fields: ['name'],
    output_fields: [{ key: 'verdict', type: 'boolean', description: '' }],
    is_active: true,
    created_by_email: 'staff@posthog.com',
    created_at: '2024-01-01T00:00:00Z',
    has_results: false,
}

// A real streamed Response, split mid-body across two chunks so the listener's buffer/line-split
// handling (not just JSON.parse of one clean line) is what's under test.
function ndjsonResponse(lines: string[]): Response {
    const body = lines.map((line) => line + '\n').join('')
    const bytes = new TextEncoder().encode(body)
    const mid = Math.floor(bytes.length / 2)
    const stream = new ReadableStream<Uint8Array>({
        start(controller) {
            controller.enqueue(bytes.slice(0, mid))
            controller.enqueue(bytes.slice(mid))
            controller.close()
        },
    })
    return new Response(stream, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } })
}

describe('aiEnrichmentLogic', () => {
    let logic: ReturnType<typeof aiEnrichmentLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/growth_ai_enrichment/labels/': { results: [] },
                '/api/growth_ai_enrichment/models/': { results: [{ id: 'gpt-5-mini' }, { id: 'gpt-5-nano' }] },
                '/api/growth_ai_enrichment/configs/': { results: [CONFIG_V1] },
            },
        })
        initKeaTests()
        logic = aiEnrichmentLogic()
        logic.mount()
    })

    describe('URL label encoding', () => {
        it('decodes a URL-encoded label (built via urls.aiEnrichment) back to its raw form', async () => {
            const rawLabel = 'weird/label with spaces & stuff'

            await expectLogic(logic, () => {
                router.actions.push(urls.aiEnrichment(rawLabel))
            }).toFinishAllListeners()

            expect(logic.values.selectedLabel).toBe(rawLabel)
        })

        it('falls back to the raw value for malformed percent-encoding rather than crashing', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/ai-enrichment/bad%zzlabel')
            }).toFinishAllListeners()

            expect(logic.values.selectedLabel).toBe('bad%zzlabel')
        })
    })

    describe('draft state machine', () => {
        it('loads a version into the editor as not dirty', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadVersionIntoEditor(CONFIG_V1)
            }).toMatchValues({
                editorPromptText: 'original prompt',
                editorModel: 'gpt-5-mini',
                editorInputFields: ['name'],
                isEditorDirty: false,
            })
        })

        it('marks the editor dirty the moment a loaded version is edited, and saving always targets a new version', async () => {
            logic.actions.loadVersionIntoEditor(CONFIG_V1)

            await expectLogic(logic, () => {
                logic.actions.setEditorPromptText('edited prompt')
            }).toMatchValues({ isEditorDirty: true })

            // Editing never mutates the loaded version's own fields - the draft is separate state,
            // which is what makes "save" always a create rather than an update.
            expect(CONFIG_V1.prompt_text).toBe('original prompt')
        })

        it('is dirty only once something is actually typed for a fresh, versionless label', () => {
            logic.actions.setSelectedLabel('brand_new_label')
            expect(logic.values.isEditorDirty).toBe(false)

            logic.actions.setEditorPromptText('a new prompt')
            expect(logic.values.isEditorDirty).toBe(true)
        })
    })

    describe('canRun', () => {
        it('requires a label, prompt, input field, and valid output field before a test run is allowed', () => {
            logic.actions.setSelectedLabel('test_label')
            expect(logic.values.canRun).toBe(false)

            logic.actions.setEditorPromptText('judge it')
            expect(logic.values.canRun).toBe(false)

            logic.actions.setEditorInputFields(['name'])
            expect(logic.values.canRun).toBe(false)

            logic.actions.addOutputField()
            logic.actions.updateOutputField(0, { key: 'verdict' })
            expect(logic.values.canRun).toBe(true)
        })
    })

    describe('saveVersion', () => {
        it('posts the current draft under the selected label at the chosen version, then selects it back in', async () => {
            let requestBody: unknown
            let saved = false
            const savedVersion: ConfigVersionApi = { ...CONFIG_V1, id: 'config-v2', version: 'v2', is_active: false }
            useMocks({
                get: {
                    // Reflects the save in the label's version list, same as a real reload would -
                    // the point under test is that the editor ends up pointed at the new row.
                    '/api/growth_ai_enrichment/configs/': () => ({
                        results: saved ? [CONFIG_V1, savedVersion] : [CONFIG_V1],
                    }),
                },
                post: {
                    '/api/growth_ai_enrichment/save/': async ({ request }) => {
                        requestBody = await request.json()
                        saved = true
                        return [201, savedVersion]
                    },
                },
            })
            // Let the label selection's own config load (and the loadVersionIntoEditor it
            // triggers) settle first, so it can't race with - and clobber - the edit below.
            await expectLogic(logic, () => {
                logic.actions.setSelectedLabel('test_label')
            }).toDispatchActions(['loadConfigsSuccess'])
            logic.actions.setEditorPromptText('a new prompt')

            await expectLogic(logic, () => {
                logic.actions.saveVersion('v2')
            }).toFinishAllListeners()

            expect(requestBody).toEqual({
                label: 'test_label',
                version: 'v2',
                prompt_text: 'a new prompt',
                model: 'gpt-5-mini',
                input_fields: ['name'],
                output_fields: [{ key: 'verdict', type: 'boolean', description: '' }],
            })
            expect(logic.values.selectedVersionId).toBe('config-v2')
        })
    })

    describe('runClassification', () => {
        it('parses ndjson rows and the trailing summary line out of a chunked stream', async () => {
            const rowLine = JSON.stringify({
                company: 'Acme',
                domain: 'acme.com',
                inputs: { name: 'Acme' },
                outputs: { verdict: true },
            })
            const summaryLine = JSON.stringify({ summary: { classified: 1, unknown: 0, errors: 0 } })
            useMocks({
                post: {
                    '/api/growth_ai_enrichment/run/': () => ndjsonResponse([rowLine, summaryLine]),
                },
            })
            // Let the label selection's own config load (and the loadVersionIntoEditor it
            // triggers) settle first - loadVersionIntoEditor resets runRows/runSummary (see the
            // "stops a stale run" tests below), so a pending one racing the run below would wipe
            // out the very rows this test asserts on.
            await expectLogic(logic, () => {
                logic.actions.setSelectedLabel('test_label')
            }).toDispatchActions(['loadConfigsSuccess'])
            logic.actions.setEditorPromptText('judge it')
            logic.actions.setEditorInputFields(['name'])
            logic.actions.addOutputField()
            logic.actions.updateOutputField(0, { key: 'verdict' })

            await expectLogic(logic, () => {
                logic.actions.runClassification()
            }).toFinishAllListeners()

            expect(logic.values.runRows).toEqual([
                { company: 'Acme', domain: 'acme.com', inputs: { name: 'Acme' }, outputs: { verdict: true } },
            ])
            expect(logic.values.runSummary).toEqual({ classified: 1, unknown: 0, errors: 0 })
            expect(logic.values.isRunning).toBe(false)
        })

        it('surfaces a terminal aborted-run error and clears isRunning, without the generic fallback toast', async () => {
            const rowLine = JSON.stringify({
                company: 'Acme',
                domain: 'acme.com',
                inputs: { name: 'Acme' },
                outputs: { verdict: true },
            })
            const errorLine = JSON.stringify({ error: 'LLM gateway timed out', aborted: true })
            useMocks({
                post: {
                    '/api/growth_ai_enrichment/run/': () => ndjsonResponse([rowLine, errorLine]),
                },
            })
            await expectLogic(logic, () => {
                logic.actions.setSelectedLabel('test_label')
            }).toDispatchActions(['loadConfigsSuccess'])
            logic.actions.setEditorPromptText('judge it')
            logic.actions.setEditorInputFields(['name'])
            logic.actions.addOutputField()
            logic.actions.updateOutputField(0, { key: 'verdict' })

            await expectLogic(logic, () => {
                logic.actions.runClassification()
            }).toFinishAllListeners()

            // The row emitted before the terminal error still lands - only the run as a whole is
            // marked failed, not the rows already streamed in.
            expect(logic.values.runRows).toEqual([
                { company: 'Acme', domain: 'acme.com', inputs: { name: 'Acme' }, outputs: { verdict: true } },
            ])
            expect(logic.values.runError).toBe('LLM gateway timed out')
            expect(logic.values.runSummary).toBeNull()
            expect(logic.values.isRunning).toBe(false)
        })

        it('is not callable again while a run is already in flight', async () => {
            useMocks({
                post: {
                    '/api/growth_ai_enrichment/run/': () => ndjsonResponse([JSON.stringify({ summary: {} })]),
                },
            })
            await expectLogic(logic, () => {
                logic.actions.setSelectedLabel('test_label')
            }).toDispatchActions(['loadConfigsSuccess'])
            logic.actions.setEditorPromptText('judge it')
            logic.actions.setEditorInputFields(['name'])
            logic.actions.addOutputField()
            logic.actions.updateOutputField(0, { key: 'verdict' })

            logic.actions.runClassification()

            expect(logic.values.isRunning).toBe(true)
            expect(logic.values.canRun).toBe(false)
        })

        it('stops a stale run and clears its rows when the label changes mid-run', async () => {
            useMocks({
                post: {
                    '/api/growth_ai_enrichment/run/': () => ndjsonResponse([JSON.stringify({ summary: {} })]),
                },
            })
            await expectLogic(logic, () => {
                logic.actions.setSelectedLabel('test_label')
            }).toDispatchActions(['loadConfigsSuccess'])
            logic.actions.setEditorPromptText('judge it')
            logic.actions.setEditorInputFields(['name'])
            logic.actions.addOutputField()
            logic.actions.updateOutputField(0, { key: 'verdict' })
            logic.actions.appendRunRow({ company: 'Stale Co', domain: null, inputs: {}, outputs: { verdict: true } })
            logic.actions.setIsRunning(true)

            logic.actions.setSelectedLabel('other_label')

            expect(logic.values.runRows).toEqual([])
            expect(logic.values.runSummary).toBeNull()
            expect(logic.values.isRunning).toBe(false)
        })

        it('stops a stale run and clears its rows when a different version is loaded mid-run', () => {
            logic.actions.appendRunRow({ company: 'Stale Co', domain: null, inputs: {}, outputs: { verdict: true } })
            logic.actions.setIsRunning(true)

            logic.actions.loadVersionIntoEditor(CONFIG_V1)

            expect(logic.values.runRows).toEqual([])
            expect(logic.values.runSummary).toBeNull()
            expect(logic.values.isRunning).toBe(false)
        })
    })
})
