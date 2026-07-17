import {
    compactInput,
    findResourceLink,
    formatInput,
    getCommandOutput,
    getContentImage,
    getContentText,
    getFilename,
    getLineCount,
    getReadToolContent,
    getResultCount,
    resolveToolCallStatus,
    stripAnsi,
    stripCodeFences,
    truncateText,
} from './toolContentUtils'

describe('toolContentUtils', () => {
    describe('resolveToolCallStatus', () => {
        it('treats an in-progress tool as loading while the turn is live', () => {
            expect(resolveToolCallStatus('in_progress', false, false)).toEqual({
                isLoading: true,
                wasCancelled: false,
                isFailed: false,
                isComplete: false,
            })
        })

        it('treats an incomplete tool as cancelled once the turn was cancelled', () => {
            const flags = resolveToolCallStatus('pending', true, false)
            expect(flags.wasCancelled).toBe(true)
            expect(flags.isLoading).toBe(false)
        })

        it('stops spinning a still-incomplete tool once the turn completes', () => {
            const flags = resolveToolCallStatus('in_progress', false, true)
            expect(flags.isLoading).toBe(false)
            expect(flags.wasCancelled).toBe(false)
        })

        it('maps terminal statuses directly', () => {
            expect(resolveToolCallStatus('failed', false, false).isFailed).toBe(true)
            expect(resolveToolCallStatus('completed', false, false).isComplete).toBe(true)
        })
    })

    describe('getContentText', () => {
        it('unwraps the ACP content envelope', () => {
            expect(getContentText([{ type: 'content', content: { type: 'text', text: 'hi' } }])).toBe('hi')
        })

        it('reads a flat text block and returns the first one', () => {
            expect(
                getContentText([
                    { type: 'text', text: 'first' },
                    { type: 'text', text: 'second' },
                ])
            ).toBe('first')
        })

        it('returns empty string when no text block is present', () => {
            expect(
                getContentText([{ type: 'content', content: { type: 'image', data: 'x', mimeType: 'image/png' } }])
            ).toBe('')
        })
    })

    describe('getCommandOutput', () => {
        it('drops a leading content block that echoes the command', () => {
            const content = [
                { type: 'text', text: 'ls -la' },
                { type: 'text', text: 'total 8\nfile.ts' },
            ]
            expect(getCommandOutput(content, 'ls -la', undefined)).toBe('total 8\nfile.ts')
        })

        it('strips a "command\\noutput" prefix from a single block', () => {
            expect(getCommandOutput([{ type: 'text', text: 'pwd\n/home/user' }], 'pwd', undefined)).toBe('/home/user')
        })

        it('returns plain output unchanged when it does not echo the command', () => {
            expect(getCommandOutput([{ type: 'text', text: 'build succeeded' }], 'pnpm build', undefined)).toBe(
                'build succeeded'
            )
        })

        it('falls back to a string rawOutput when the command produced no content', () => {
            expect(getCommandOutput([{ type: 'text', text: 'echo hi' }], 'echo hi', 'hi')).toBe('hi')
        })
    })

    describe('getReadToolContent', () => {
        it('strips system reminders, code fences, and arrow line-number gutters', () => {
            const raw =
                '```python\n     1→import os\n     2→print(os.getcwd())\n```\n<system-reminder>be careful</system-reminder>'
            expect(getReadToolContent([{ type: 'text', text: raw }])).toBe('import os\nprint(os.getcwd())')
        })

        it('strips tab-delimited line-number gutters (the Read tool output format)', () => {
            const raw = '```\n1\t---\n2\ttitle: x\n3\t\n10\tconst a = 1\n```'
            expect(getReadToolContent([{ type: 'text', text: raw }])).toBe('---\ntitle: x\n\nconst a = 1')
        })
    })

    describe('getContentImage', () => {
        it('returns the base64 + mime of the first image block', () => {
            expect(
                getContentImage([{ type: 'content', content: { type: 'image', data: 'AAAA', mimeType: 'image/png' } }])
            ).toEqual({ base64: 'AAAA', mimeType: 'image/png' })
        })

        it('returns null when there is no image block', () => {
            expect(getContentImage([{ type: 'text', text: 'no image' }])).toBeNull()
        })
    })

    describe('findResourceLink', () => {
        it('returns the first resource_link block', () => {
            expect(
                findResourceLink([{ type: 'resource_link', uri: 'https://x.com', name: 'X', description: 'a site' }])
            ).toEqual({ uri: 'https://x.com', name: 'X', description: 'a site' })
        })
    })

    describe('stripAnsi', () => {
        it('removes SGR colour codes', () => {
            expect(stripAnsi('[31mred[0m text')).toBe('red text')
        })
    })

    describe('stripCodeFences', () => {
        it('removes leading and trailing fences', () => {
            expect(stripCodeFences('```ts\nconst a = 1\n```')).toBe('const a = 1')
        })

        it('leaves unfenced text untouched', () => {
            expect(stripCodeFences('plain text')).toBe('plain text')
        })
    })

    describe('counts and truncation', () => {
        it('counts non-empty result lines', () => {
            expect(getResultCount('a.ts\n\nb.ts\nc.ts\n')).toBe(3)
        })

        it('counts total lines, treating blank text as zero', () => {
            expect(getLineCount('one\ntwo')).toBe(2)
            expect(getLineCount('   ')).toBe(0)
        })

        it('truncates with an ellipsis only when over the limit', () => {
            expect(truncateText('short', 10)).toBe('short')
            expect(truncateText('abcdef', 3)).toBe('abc…')
        })

        it('extracts the basename', () => {
            expect(getFilename('a/b/c.ts')).toBe('c.ts')
            expect(getFilename('flat.ts')).toBe('flat.ts')
        })
    })

    describe('input previews', () => {
        it('compacts input JSON to a single truncated line', () => {
            expect(compactInput({ a: 1 })).toBe('{"a":1}')
            expect(compactInput({ key: 'a-very-long-value-that-keeps-going-and-going-and-going' }, 10)).toHaveLength(11)
        })

        it('pretty-prints input JSON', () => {
            expect(formatInput({ a: 1 })).toBe('{\n  "a": 1\n}')
        })
    })
})
