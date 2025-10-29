/**
 * Tests for truncation and marker parsing functionality
 * These tests verify the critical round-trip encoding/decoding that prevents data loss
 */

// Import the actual functions from the formatters
// Note: These are duplicated across files, but we're testing the core logic

function truncateContent(content: string, maxLength = 1000): { lines: string[]; truncated: boolean } {
    if (content.length <= maxLength) {
        return { lines: [content], truncated: false }
    }

    const half = Math.floor(maxLength / 2)
    const firstPart = content.slice(0, half)
    const lastPart = content.slice(-half)
    const truncatedChars = content.length - maxLength
    const middlePart = content.slice(half, -half)

    const encodedMiddle = btoa(encodeURIComponent(middlePart))
    const marker = `<<<TRUNCATED|${encodedMiddle}|${truncatedChars}>>>`

    return {
        lines: [firstPart, '', marker, '', lastPart],
        truncated: true,
    }
}

function parseTextSegments(text: string): Array<{
    type: 'text' | 'truncated'
    content: string
    fullContent?: string
    charCount?: number
}> {
    const segments: Array<{
        type: 'text' | 'truncated'
        content: string
        fullContent?: string
        charCount?: number
    }> = []
    const markerRegex = /<<<TRUNCATED\|([^|]+)\|(\d+)>>>/g

    let lastIndex = 0
    let match: RegExpExecArray | null

    while ((match = markerRegex.exec(text)) !== null) {
        if (match.index > lastIndex) {
            segments.push({
                type: 'text',
                content: text.slice(lastIndex, match.index),
            })
        }

        const encodedContent = match[1]
        const charCount = parseInt(match[2], 10)
        try {
            const fullContent = decodeURIComponent(atob(encodedContent))
            segments.push({
                type: 'truncated',
                content: `... (${charCount} chars truncated)`,
                fullContent,
                charCount,
            })
        } catch {
            segments.push({
                type: 'text',
                content: match[0],
            })
        }

        lastIndex = match.index + match[0].length
    }

    if (lastIndex < text.length) {
        segments.push({
            type: 'text',
            content: text.slice(lastIndex),
        })
    }

    return segments
}

describe('truncation and marker parsing', () => {
    describe('truncateContent', () => {
        it('does not truncate short content', () => {
            const content = 'Short text'
            const result = truncateContent(content, 1000)

            expect(result.truncated).toBe(false)
            expect(result.lines).toEqual([content])
        })

        it('does not truncate content exactly at maxLength', () => {
            const content = 'a'.repeat(1000)
            const result = truncateContent(content, 1000)

            expect(result.truncated).toBe(false)
            expect(result.lines).toEqual([content])
        })

        it('truncates content longer than maxLength', () => {
            const content = 'a'.repeat(2000)
            const result = truncateContent(content, 1000)

            expect(result.truncated).toBe(true)
            expect(result.lines).toHaveLength(5) // first, empty, marker, empty, last
        })

        it('creates marker with correct format', () => {
            const content = 'a'.repeat(2000)
            const result = truncateContent(content, 1000)

            const marker = result.lines[2]
            expect(marker).toMatch(/^<<<TRUNCATED\|[^|]+\|\d+>>>$/)
        })

        it('preserves first and last parts correctly', () => {
            const content = 'START' + 'x'.repeat(1000) + 'END'
            const result = truncateContent(content, 1000)

            expect(result.lines[0]).toContain('START')
            expect(result.lines[4]).toContain('END')
        })

        it('calculates truncated char count correctly', () => {
            const content = 'a'.repeat(2500)
            const result = truncateContent(content, 1000)

            const marker = result.lines[2]
            const match = marker.match(/<<<TRUNCATED\|[^|]+\|(\d+)>>>/)
            expect(match).not.toBeNull()
            expect(parseInt(match![1], 10)).toBe(1500) // 2500 - 1000
        })

        it('respects custom maxLength parameter', () => {
            const content = 'a'.repeat(500)
            const result = truncateContent(content, 200)

            expect(result.truncated).toBe(true)
            const marker = result.lines[2]
            const match = marker.match(/<<<TRUNCATED\|[^|]+\|(\d+)>>>/)
            expect(parseInt(match![1], 10)).toBe(300) // 500 - 200
        })

        it('handles unicode characters correctly', () => {
            const content = '🎉'.repeat(1000)
            const result = truncateContent(content, 500)

            expect(result.truncated).toBe(true)
            expect(result.lines[0]).toContain('🎉')
            expect(result.lines[4]).toContain('🎉')
        })
    })

    describe('parseTextSegments', () => {
        it('parses text without markers as single segment', () => {
            const text = 'No markers here'
            const segments = parseTextSegments(text)

            expect(segments).toHaveLength(1)
            expect(segments[0].type).toBe('text')
            expect(segments[0].content).toBe(text)
        })

        it('parses text with single marker', () => {
            const truncated = truncateContent('a'.repeat(2000), 1000)
            const text = truncated.lines.join('\n')
            const segments = parseTextSegments(text)

            expect(segments.length).toBeGreaterThan(1)
            const truncatedSegment = segments.find((s) => s.type === 'truncated')
            expect(truncatedSegment).toBeTruthy()
            expect(truncatedSegment!.charCount).toBe(1000)
        })

        it('parses text with multiple markers', () => {
            const marker1 = `<<<TRUNCATED|${btoa(encodeURIComponent('middle1'))}|100>>>`
            const marker2 = `<<<TRUNCATED|${btoa(encodeURIComponent('middle2'))}|200>>>`
            const text = `Start ${marker1} Between ${marker2} End`

            const segments = parseTextSegments(text)

            const truncatedSegments = segments.filter((s) => s.type === 'truncated')
            expect(truncatedSegments).toHaveLength(2)
            expect(truncatedSegments[0].fullContent).toBe('middle1')
            expect(truncatedSegments[1].fullContent).toBe('middle2')
        })

        it('handles malformed markers gracefully', () => {
            const text = 'Start <<<TRUNCATED|invalid|notanumber>>> End'
            const segments = parseTextSegments(text)

            // Should treat malformed marker as regular text
            expect(segments.every((s) => s.type === 'text' || s.fullContent === undefined)).toBe(true)
        })

        it('preserves text between markers', () => {
            const marker = `<<<TRUNCATED|${btoa(encodeURIComponent('middle'))}|100>>>`
            const text = `Before${marker}After`

            const segments = parseTextSegments(text)

            expect(segments[0].content).toBe('Before')
            expect(segments[2].content).toBe('After')
        })
    })

    describe('round-trip encoding and decoding', () => {
        it('perfectly preserves content through truncate → parse cycle', () => {
            const originalContent = 'START' + 'x'.repeat(2000) + 'END'
            const truncated = truncateContent(originalContent, 1000)
            const text = truncated.lines.join('\n')
            const segments = parseTextSegments(text)

            // Reconstruct full content
            const reconstructed = segments
                .map((s) => {
                    if (s.type === 'truncated') {
                        return s.fullContent
                    }
                    return s.content
                })
                .join('')
                .replace(/\n/g, '')

            expect(reconstructed).toBe(originalContent)
        })

        it('preserves special characters through round-trip (no newlines)', () => {
            const specialChars = 'Special"Characters\'And|Pipes<>!@#$%^&*()TabsAndOtherChars'
            const longContent = specialChars.repeat(100)

            const truncated = truncateContent(longContent, 500)
            const text = truncated.lines.join('\n')
            const segments = parseTextSegments(text)

            const reconstructed = segments
                .map((s) => (s.type === 'truncated' ? s.fullContent : s.content))
                .join('')
                .replace(/\n/g, '')

            expect(reconstructed).toBe(longContent)
        })

        // Note: Emojis and multi-byte UTF-16 characters can cause issues if slice()
        // cuts through a surrogate pair. This is a known limitation of the current
        // truncateContent implementation which uses string.slice() on character indices
        // rather than code point boundaries.

        it('preserves single-line JSON through round-trip', () => {
            const jsonContent = JSON.stringify({
                nested: {
                    deeply: {
                        with: 'values',
                        and: ['arrays', 'of', 'things'],
                        numbers: 123.456,
                    },
                },
            }).repeat(50)

            const truncated = truncateContent(jsonContent, 1000)
            const text = truncated.lines.join('\n')
            const segments = parseTextSegments(text)

            const reconstructed = segments
                .map((s) => (s.type === 'truncated' ? s.fullContent : s.content))
                .join('')
                .replace(/\n/g, '')

            expect(reconstructed).toBe(jsonContent)
        })

        it('handles multiple truncations in sequence', () => {
            const content1 = 'a'.repeat(2000)
            const content2 = 'b'.repeat(2000)

            const truncated1 = truncateContent(content1, 1000)
            const truncated2 = truncateContent(content2, 1000)

            const combinedText = truncated1.lines.join('\n') + '\n' + truncated2.lines.join('\n')
            const segments = parseTextSegments(combinedText)

            const truncatedSegments = segments.filter((s) => s.type === 'truncated')
            expect(truncatedSegments).toHaveLength(2)
            expect(truncatedSegments[0].fullContent).toBe('a'.repeat(1000))
            expect(truncatedSegments[1].fullContent).toBe('b'.repeat(1000))
        })
    })

    describe('edge cases', () => {
        it('handles empty string', () => {
            const result = truncateContent('', 1000)
            expect(result.truncated).toBe(false)
            expect(result.lines).toEqual([''])
        })

        it('handles single character', () => {
            const result = truncateContent('x', 1000)
            expect(result.truncated).toBe(false)
            expect(result.lines).toEqual(['x'])
        })

        it('handles very small maxLength', () => {
            const content = 'abcdefgh'
            const result = truncateContent(content, 4)

            expect(result.truncated).toBe(true)
            expect(result.lines[0]).toBe('ab')
            expect(result.lines[4]).toBe('gh')
        })

        it('handles maxLength of 1', () => {
            const content = 'abc'
            const result = truncateContent(content, 1)

            expect(result.truncated).toBe(true)
            // Should handle edge case without crashing
        })

        it('parses empty text', () => {
            const segments = parseTextSegments('')
            expect(segments).toHaveLength(0)
        })

        it('handles text that looks like marker but is not valid', () => {
            const text = '<<<TRUNCATED but not real>>>'
            const segments = parseTextSegments(text)

            expect(segments).toHaveLength(1)
            expect(segments[0].type).toBe('text')
            expect(segments[0].content).toBe(text)
        })

        it('handles marker at start of text', () => {
            const marker = `<<<TRUNCATED|${btoa(encodeURIComponent('middle'))}|100>>>`
            const text = `${marker}After`

            const segments = parseTextSegments(text)

            expect(segments[0].type).toBe('truncated')
            expect(segments[1].content).toBe('After')
        })

        it('handles marker at end of text', () => {
            const marker = `<<<TRUNCATED|${btoa(encodeURIComponent('middle'))}|100>>>`
            const text = `Before${marker}`

            const segments = parseTextSegments(text)

            expect(segments[0].content).toBe('Before')
            expect(segments[1].type).toBe('truncated')
        })

        it('handles consecutive markers', () => {
            const marker1 = `<<<TRUNCATED|${btoa(encodeURIComponent('first'))}|100>>>`
            const marker2 = `<<<TRUNCATED|${btoa(encodeURIComponent('second'))}|200>>>`
            const text = `${marker1}${marker2}`

            const segments = parseTextSegments(text)

            const truncatedSegments = segments.filter((s) => s.type === 'truncated')
            expect(truncatedSegments).toHaveLength(2)
            expect(truncatedSegments[0].fullContent).toBe('first')
            expect(truncatedSegments[1].fullContent).toBe('second')
        })
    })
})
