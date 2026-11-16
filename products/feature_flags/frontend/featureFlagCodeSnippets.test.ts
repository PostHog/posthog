import { Language } from 'lib/components/CodeSnippet'

import { dedentSnippet, languageForFile, sortBranches } from './featureFlagCodeSnippets'

describe('languageForFile', () => {
    it.each([
        ['frontend/src/Header.tsx', Language.TypeScript],
        ['server/index.mjs', Language.JavaScript],
        ['app/src/Main.kt', Language.Kotlin],
        ['src/lib.rs', Language.Rust],
        ['Services/Flags.cs', Language.CSharp],
    ])('reads %s as %s', (path, language) => {
        expect(languageForFile(path)).toBe(language)
    })
})

describe('dedentSnippet', () => {
    it('removes the indentation every line shares', () => {
        expect(dedentSnippet('        if (a) {\n            run()\n        }')).toBe('if (a) {\n    run()\n}')
    })

    it('dedents the other lines on their own when the first line lost its indentation', () => {
        expect(dedentSnippet('<div>\n            <Search />\n        </div>')).toBe('<div>\n    <Search />\n</div>')
    })

    it('ignores blank lines when measuring the shared indentation', () => {
        expect(dedentSnippet('    first()\n\n    second()\n')).toBe('first()\n\nsecond()')
    })
})

describe('sortBranches', () => {
    it('puts the off outcome before the on outcome and control before other variants', () => {
        const branch = (
            variant: string
        ): { variant: string; start_line: number; end_line: number; snippet: string } => ({
            variant,
            start_line: 1,
            end_line: 1,
            snippet: '',
        })
        const sorted = sortBranches([branch('test'), branch('control'), branch('enabled'), branch('disabled')])
        expect(sorted.map((b) => b.variant)).toEqual(['disabled', 'enabled', 'control', 'test'])
    })
})
