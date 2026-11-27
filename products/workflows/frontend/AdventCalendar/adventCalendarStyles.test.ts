import fs from 'fs'
import path from 'path'
import postcss, { AtRule, Root } from 'postcss'

// The frontend package, which runs these tests, depends on sass. A require keeps this product from
// declaring a second copy only for its types.
const { compileString }: { compileString: (source: string) => { css: string } } = require('sass')

// The calendar animates on a page people keep open for minutes. These rules keep its motion on the
// compositor: a blend mode or filter makes the compositor redraw the whole stage on every animated
// frame, a keyframe on any other property repaints on the main thread, and a container unit in any
// keyframes or a var() in the keyframes of an endless animation adds style work to every frame the
// page renders. A one-shot animation, such as a reveal burst, may read a var() because it pays that
// cost for less than a second after a click and then stops.
const CONTAINER_UNIT = /\d(cq[whib]|cqmin|cqmax)\b/
const COMPOSITED_PROPERTIES = new Set(['transform', 'opacity'])
const EXPENSIVE_PROPERTIES = new Set(['mix-blend-mode', 'filter', 'backdrop-filter'])

function stylesheets(directory: string): string[] {
    return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const file = path.join(directory, entry.name)
        if (entry.isDirectory()) {
            return stylesheets(file)
        }
        return entry.name.endsWith('.scss') ? [file] : []
    })
}

function endlessAnimationNames(root: Root): Set<string> {
    const names = new Set<string>()
    root.walkDecls(/^animation(-name)?$/, (declaration) => {
        const rule = declaration.parent
        const isEndless =
            declaration.value.includes('infinite') ||
            !!rule?.some(
                (node) => node.type === 'decl' && node.prop === 'animation-iteration-count' && node.value === 'infinite'
            )
        if (isEndless) {
            declaration.value.split(/[\s,]+/).forEach((token) => names.add(token))
        }
    })
    return names
}

const files = stylesheets(__dirname)

describe('advent calendar styles', () => {
    it('finds the stylesheets', () => {
        expect(files.map((file) => path.basename(file))).toContain('AdventSnow.scss')
    })

    test.each(files.map((file) => [path.relative(__dirname, file), file]))(
        '%s keeps its animations on the compositor',
        (_, file) => {
            const root = postcss.parse(compileString(fs.readFileSync(file, 'utf8')).css)
            const problems: string[] = []

            root.walkDecls((declaration) => {
                if (EXPENSIVE_PROPERTIES.has(declaration.prop)) {
                    problems.push(`${declaration.prop} on ${(declaration.parent as { selector?: string }).selector}`)
                }
            })

            const endless = endlessAnimationNames(root)
            root.walkAtRules('keyframes', (keyframes: AtRule) => {
                keyframes.walkDecls((declaration) => {
                    if (!COMPOSITED_PROPERTIES.has(declaration.prop)) {
                        problems.push(`@keyframes ${keyframes.params} animates ${declaration.prop}`)
                    }
                    if (CONTAINER_UNIT.test(declaration.value)) {
                        problems.push(`@keyframes ${keyframes.params} reads a container unit`)
                    }
                    if (endless.has(keyframes.params) && declaration.value.includes('var(')) {
                        problems.push(`@keyframes ${keyframes.params} runs forever and reads a var()`)
                    }
                })
            })

            expect(problems).toEqual([])
        }
    )
})
