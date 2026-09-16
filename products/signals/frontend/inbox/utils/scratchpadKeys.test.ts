import { scratchpadKindOf, scratchpadTopicOf } from './scratchpadKeys'

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
})
