import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayScannerTemplateApi } from '../generated/api.schemas'
import { scannerTemplatesLogic } from './scannerTemplatesLogic'

const template = (id: string, sourceScanner: string): ReplayScannerTemplateApi => ({
    id,
    name: `Template ${id}`,
    description: 'Reusable scanner configuration',
    scanner_type: 'monitor',
    scanner_config: { prompt: 'What did the user do next?' },
    query: { kind: 'RecordingsQuery' },
    sampling_rate: 1,
    sampling_mode: 'comprehensive',
    provider: 'google',
    model: 'gemini-3-flash-preview',
    emits_signals: false,
    source_scanner: sourceScanner,
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

describe('scannerTemplatesLogic', () => {
    let logic: ReturnType<typeof scannerTemplatesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanner_templates/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [template('saved', 'scanner-1')],
                },
            },
            post: {
                '/api/projects/:team/vision/scanners/:id/save_as_template/': () => [201, template('new', 'scanner-2')],
            },
            delete: {
                '/api/projects/:team/vision/scanner_templates/:id/': () => [204, null],
            },
        })
        initKeaTests()
        logic = scannerTemplatesLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('loads, saves, and deletes reusable scanner templates', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadTemplatesSuccess'])
            .toMatchValues({
                customTemplates: [expect.objectContaining({ id: 'saved' })],
            })

        await expectLogic(logic, () => logic.actions.saveTemplate('scanner-2'))
            .toFinishAllListeners()
            .toMatchValues({
                customTemplates: [expect.objectContaining({ id: 'new' }), expect.objectContaining({ id: 'saved' })],
                savingScannerIds: [],
            })

        await expectLogic(logic, () => logic.actions.deleteTemplate('saved'))
            .toFinishAllListeners()
            .toMatchValues({
                customTemplates: [expect.objectContaining({ id: 'new' })],
                deletingTemplateIds: [],
            })
    })

    it('pages through every template instead of dropping ones past the first page', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        const page1 = Array.from({ length: 100 }, (_, i) => template(`p1-${i}`, `s-p1-${i}`))
        const page2 = Array.from({ length: 50 }, (_, i) => template(`p2-${i}`, `s-p2-${i}`))
        let call = 0
        useMocks({
            get: {
                '/api/projects/:team/vision/scanner_templates/': () => {
                    call += 1
                    return call === 1
                        ? [200, { count: 150, next: 'next', previous: null, results: page1 }]
                        : [200, { count: 150, next: null, previous: null, results: page2 }]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.loadTemplates()).toDispatchActions(['loadTemplatesSuccess'])
        expect(logic.values.customTemplates).toHaveLength(150)
    })
})
