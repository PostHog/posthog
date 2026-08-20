import { SAMPLING_MODE_OPTIONS } from '../types'
import { diffVersionConfigs, VersionConfig, versionChangesByVersion } from './versionChanges'

describe('versionChanges', () => {
    const version = (overrides: Partial<VersionConfig> = {}): VersionConfig => ({
        version: 1,
        scannerType: 'classifier',
        model: 'gemini-3.7-flash',
        provider: 'google',
        emitsSignals: true,
        samplingRate: 1,
        samplingMode: 'balanced',
        query: { kind: 'RecordingsQuery', events: [] },
        scannerConfig: { prompt: 'classify this', tags: ['a', 'b'] },
        ...overrides,
    })

    describe('diffVersionConfigs', () => {
        it.each([
            // The real bug this readout exists for: turning a flag on bumped the version, and the history
            // showed nothing because the previous config had no such key at all.
            ['a flag absent before', { prompt: 'p' }, { prompt: 'p', multi_label: true }, 'off', 'on'],
            ['a flag removed', { prompt: 'p', multi_label: true }, { prompt: 'p' }, 'on', 'off'],
            ['a flag flipped', { prompt: 'p', multi_label: true }, { prompt: 'p', multi_label: false }, 'on', 'off'],
        ])('reports %s', (_name, beforeConfig, afterConfig, before, after) => {
            const { changes } = diffVersionConfigs(
                version({ scannerConfig: beforeConfig }),
                version({ version: 2, scannerConfig: afterConfig })
            )
            expect(changes).toEqual([
                { field: 'multi_label', label: 'Multiple categories per session', kind: 'value', before, after },
            ])
        })

        it.each([
            ['model', { model: 'gemini-3.5-flash-lite' }, 'Model'],
            ['sampling rate', { samplingRate: 0.25 }, 'Sampling'],
            ['session coverage', { samplingMode: 'focused' }, 'Session coverage'],
            ['signal emission', { emitsSignals: false }, 'Emit signals'],
            ['type', { scannerType: 'monitor' }, 'Type'],
        ])('reports a changed %s', (_name, overrides, label) => {
            const { changes } = diffVersionConfigs(version(), version({ version: 2, ...overrides }))
            expect(changes.map((change) => change.label)).toEqual([label])
        })

        it('formats sampling and coverage with the labels the configuration tab uses', () => {
            // Read the copy from the option list rather than pinning it, so renaming a mode isn't a test failure.
            const modeLabel = (value: string): string =>
                SAMPLING_MODE_OPTIONS.find((option) => option.value === value)?.label ?? value
            const { changes } = diffVersionConfigs(
                version(),
                version({ version: 2, samplingRate: 0.255, samplingMode: 'focused' })
            )
            expect(changes).toEqual([
                {
                    field: 'samplingMode',
                    label: 'Session coverage',
                    kind: 'value',
                    before: modeLabel('balanced'),
                    after: modeLabel('focused'),
                },
                { field: 'samplingRate', label: 'Sampling', kind: 'value', before: '100%', after: '25.5%' },
            ])
            // The raw enum leaking through instead of the friendly label is the regression this guards.
            expect(changes[0].after).not.toBe('focused')
        })

        it('carries the raw prompt text so the change can be diffed, and puts it first', () => {
            const { changes } = diffVersionConfigs(
                version({ scannerConfig: { prompt: 'old', multi_label: false } }),
                version({ version: 2, scannerConfig: { prompt: 'new', multi_label: true } })
            )
            expect(changes[0]).toEqual({
                field: 'prompt',
                label: 'Prompt',
                kind: 'prompt',
                before: 'old',
                after: 'new',
            })
            expect(changes).toHaveLength(2)
        })

        it('reports a changed query once, without trying to summarize it in a line', () => {
            const { changes } = diffVersionConfigs(
                version(),
                version({ version: 2, query: { kind: 'RecordingsQuery', events: [{ id: '$pageview' }] } })
            )
            expect(changes).toEqual([
                { field: 'query', label: 'Recording filters', kind: 'query', before: '', after: '' },
            ])
        })

        it.each([
            ['the older version', { query: null }, {}],
            ['the newer version', {}, { query: null }],
        ])('treats a query missing from %s as not recorded, not as a change', (_name, before, after) => {
            const result = diffVersionConfigs(version(before), version({ version: 2, ...after }))
            expect(result.changes).toEqual([])
            expect(result.notRecorded).toEqual(['Recording filters'])
        })

        it('lists every unrecorded field for versions scanned before they were snapshotted', () => {
            const legacy = { model: null, provider: null, query: null, samplingRate: null, samplingMode: null }
            const result = diffVersionConfigs(version(legacy), version({ version: 2, ...legacy }))
            expect(result.changes).toEqual([])
            expect(result.notRecorded).toEqual([
                'Model',
                'Provider',
                'Session coverage',
                'Sampling',
                'Recording filters',
            ])
        })

        it('reports nothing for identical versions', () => {
            const result = diffVersionConfigs(version(), version({ version: 2 }))
            expect(result.changes).toEqual([])
            expect(result.notRecorded).toEqual([])
            expect(result.previous.version).toBe(1)
        })
    })

    describe('versionChangesByVersion', () => {
        it('compares against the previous version present, not the previous number', () => {
            // v2 and v3 scanned nothing, so they have no entry to compare against.
            const result = versionChangesByVersion([
                version({ version: 4, scannerConfig: { prompt: 'b' } }),
                version({ version: 1, scannerConfig: { prompt: 'a' } }),
            ])
            expect([...result.keys()]).toEqual([4])
            expect(result.get(4)?.previous.version).toBe(1)
            expect(result.get(4)?.changes.map((change) => change.label)).toEqual(['Prompt'])
        })
    })
})
