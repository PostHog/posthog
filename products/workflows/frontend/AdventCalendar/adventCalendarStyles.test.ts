import fs from 'fs'
import path from 'path'
import postcss, { AtRule, Root } from 'postcss'

const { compileString }: { compileString: (source: string) => { css: string } } = require('sass')

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

function oneShotAnimationNames(root: Root): Set<string> {
    const named = new Map<string, boolean>()
    let anyEndlessCount = false
    root.walkDecls(/^animation(-name|-iteration-count)?$/, (declaration) => {
        if (declaration.prop === 'animation-iteration-count') {
            anyEndlessCount ||= declaration.value.includes('infinite')
            return
        }
        const finite = declaration.prop === 'animation' && !declaration.value.includes('infinite')
        declaration.value.split(/[\s,]+/).forEach((token) => named.set(token, (named.get(token) ?? true) && finite))
    })
    return new Set(anyEndlessCount ? [] : [...named].filter(([, finite]) => finite).map(([name]) => name))
}

const files = stylesheets(__dirname)

describe('advent calendar styles', () => {
    test.each(files.map((file) => [path.relative(__dirname, file), file]))(
        '%s uses no blend mode or filter, and its keyframes animate only transform and opacity, read no container unit, and read a var() only when they run once',
        (_, file) => {
            const root = postcss.parse(compileString(fs.readFileSync(file, 'utf8')).css)
            const problems: string[] = []

            root.walkDecls((declaration) => {
                if (EXPENSIVE_PROPERTIES.has(declaration.prop)) {
                    problems.push(`${declaration.prop} on ${(declaration.parent as { selector?: string }).selector}`)
                }
            })

            const oneShot = oneShotAnimationNames(root)
            root.walkAtRules('keyframes', (keyframes: AtRule) => {
                keyframes.walkDecls((declaration) => {
                    if (!COMPOSITED_PROPERTIES.has(declaration.prop)) {
                        problems.push(`@keyframes ${keyframes.params} animates ${declaration.prop}`)
                    }
                    if (CONTAINER_UNIT.test(declaration.value)) {
                        problems.push(`@keyframes ${keyframes.params} reads a container unit`)
                    }
                    if (!oneShot.has(keyframes.params) && declaration.value.includes('var(')) {
                        problems.push(`@keyframes ${keyframes.params} may loop and reads a var()`)
                    }
                })
            })

            expect(problems).toEqual([])
        }
    )
})
