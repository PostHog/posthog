import { scratchpadKindOf, scratchpadReportIdOf, scratchpadTopicOf } from './scratchpadKeys'

const UUID = '01a0918c-5f5f-74c4-b539-c634a8cb990a'

// The prefixes the scout memory contract defines for the fleet. One missing from the registry
// parses as a topic rather than a kind, so every key carrying it reports its prefix as its topic
// and the ledger's Topic filter answers with the wrong rows.
const DOCUMENTED_PREFIXES = [
    'pattern',
    'watch',
    'noise',
    'addressed',
    'dedupe',
    'allowlist',
    'not-in-use',
    'mcp-gap',
    'improve',
    'reported',
    'report',
    'reviewer',
]

describe('scratchpadKeys', () => {
    it.each(DOCUMENTED_PREFIXES)('reads %s as a kind and the next segment as the topic', (prefix) => {
        expect(scratchpadKindOf(`${prefix}:error_tracking:entity`)).toBe(prefix)
        expect(scratchpadTopicOf(`${prefix}:error_tracking:entity`)).toBe('error_tracking')
    })

    // Scouts coin their own namespaces, and the registry is what keeps one of those from becoming
    // a ledger kind. A parser that trusted every prefix would lose the topic on these keys.
    it('treats a prefix the fleet does not use as a kind as the topic itself', () => {
        expect(scratchpadKindOf('billing_spikes:34316')).toBeNull()
        expect(scratchpadTopicOf('billing_spikes:34316')).toBe('billing_spikes')
    })

    // Every id the ledger takes for a report costs a request, and an id of anything else answers 404
    // on every page load. Only the per-report bookkeeping kinds name a report in the topic.
    it.each([
        [`judged:${UUID}`, UUID],
        [`followup:${UUID}:pr`, UUID],
        [`report:${UUID}`, UUID],
        [`${UUID}:pattern:cursor`, null],
        [`noise:${UUID}:email`, null],
        [`baseline:${UUID}:email`, null],
        [`products:${UUID}`, null],
        ['report:error_tracking:issue', null],
    ])('reads the report id of %s as %s', (key, reportId) => {
        expect(scratchpadReportIdOf(key)).toBe(reportId)
    })
})
