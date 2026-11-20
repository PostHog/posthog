import { CHAT_DICTATION_PHRASES, chatDictationPhrases } from './chatDictationPhrases'

test('uses distinct PostHog and common product terms within the platform limit by default', () => {
    const hints = chatDictationPhrases()
    expect(hints).toHaveLength(100)
    expect(new Set(hints).size).toBe(hints.length)
    expect(hints[0]).toBe('PostHog')
    expect(hints).toEqual(expect.arrayContaining(['HogQL', 'Product analytics', 'Session replay', 'Feature flags']))
})

test('prioritizes relevant vocabulary using draft terms without passing draft content to recognition', () => {
    const hints = chatDictationPhrases('Investigate Streamlit apps, WEBMCP, AEO, and the Wizard on my example draft.')
    expect(hints.slice(0, 10)).toEqual(expect.arrayContaining(['Streamlit apps', 'WebMCP', 'AEO', 'Wizard']))
    expect(hints).toHaveLength(100)
    expect(hints.every((hint) => CHAT_DICTATION_PHRASES.includes(hint))).toBe(true)
})

test('includes vocabulary from across the product registry and common engineering terms', () => {
    expect(CHAT_DICTATION_PHRASES).toEqual(
        expect.arrayContaining([
            'AI training',
            'Business intelligence',
            'Data tools',
            'MCP servers',
            'Cross-project dashboards',
            'Warehouse suggestions',
            'Incremental sync',
            'Symbolication',
        ])
    )
})
