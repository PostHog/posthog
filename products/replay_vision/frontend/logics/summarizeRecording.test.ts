import type { ReplayScannerApi, ScanOutcomeEnumApi } from '../generated/api.schemas'
import {
    BUILT_IN_SUMMARIZER,
    type SummarizeOutcomeMessage,
    resolveSummarizer,
    summarizeOutcomeMessage,
} from './summarizeRecording'

const summarizer = (id: string): ReplayScannerApi => ({ id, name: id, scanner_type: 'summarizer' }) as ReplayScannerApi
const monitor = (id: string): ReplayScannerApi => ({ id, name: id, scanner_type: 'monitor' }) as ReplayScannerApi

describe('summarizeRecording', () => {
    // The inline scan answers 202 even when it started nothing, so an outcome that falls through to a
    // success toast tells the user a summary is coming when the quota or the in-flight cap refused it.
    it.each<[ScanOutcomeEnumApi | undefined, SummarizeOutcomeMessage['level']]>([
        ['started', 'success'],
        ['already_running', 'info'],
        ['skipped_quota', 'warning'],
        ['skipped_limit', 'warning'],
        ['failed', 'error'],
        [undefined, 'error'],
    ])('reports %s as %s', (outcome, level) => {
        expect(summarizeOutcomeMessage(outcome).level).toBe(level)
    })

    // Null means the built-in prompt. The two ways of arriving there differ: no usable preference and
    // nothing unambiguous to pick, versus the user asking for it, which has to survive owning a scanner.
    it.each<[string, ReplayScannerApi[], string | null, string | null]>([
        ['a lone summarizer needs no preference', [summarizer('s1')], null, 's1'],
        ['other scanner types do not make it ambiguous', [summarizer('s1'), monitor('m1')], null, 's1'],
        ['several summarizers are ambiguous', [summarizer('s1'), summarizer('s2')], null, null],
        ['a stored pick wins', [summarizer('s1'), summarizer('s2')], 's2', 's2'],
        ['a deleted pick falls back', [summarizer('s1')], 'gone', 's1'],
        ['choosing the built-in prompt sticks', [summarizer('s1')], BUILT_IN_SUMMARIZER, null],
    ])('%s', (_, scanners, preferredId, expectedId) => {
        expect(resolveSummarizer(scanners, preferredId)?.id ?? null).toBe(expectedId)
    })
})
