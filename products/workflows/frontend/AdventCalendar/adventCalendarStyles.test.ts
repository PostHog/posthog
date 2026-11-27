import fs from 'fs'
import path from 'path'
import postcss, { AtRule, Root } from 'postcss'

const { compileString }: { compileString: (source: string) => { css: string } } = require('sass')

const CONTAINER_UNIT = /\d(cq[whib]|cqmin|cqmax)\b/
const COMPOSITED_PROPERTIES = new Set(['transform', 'opacity'])
const FORBIDDEN_PROPERTIES = new Set(['mix-blend-mode', 'filter', 'backdrop-filter', 'animation-iteration-count'])

function stylesheets(directory: string): string[] {
    return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const file = path.join(directory, entry.name)
        if (entry.isDirectory()) {
            return stylesheets(file)
        }
        return entry.name.endsWith('.scss') ? [file] : []
    })
}

function loopingAnimationNames(roots: Root[]): Set<string> {
    const names = new Set<string>()
    for (const root of roots) {
        root.walkDecls(/^animation(-name)?$/, (declaration) => {
            if (declaration.prop === 'animation-name' || declaration.value.includes('infinite')) {
                declaration.value.split(/[\s,]+/).forEach((token) => names.add(token))
            }
        })
    }
    return names
}

const sheets = stylesheets(__dirname).map((file) => ({
    name: path.relative(__dirname, file),
    root: postcss.parse(compileString(fs.readFileSync(file, 'utf8')).css),
}))
const looping = loopingAnimationNames(sheets.map(({ root }) => root))

describe('advent calendar styles', () => {
    test.each(sheets.map((sheet) => [sheet.name, sheet.root]))(
        '%s uses no blend mode, filter or separate iteration count, and its keyframes animate only transform and opacity, read no container unit, and read a var() only when no calendar stylesheet loops them',
        (_, root) => {
            const problems: string[] = []

            root.walkDecls((declaration) => {
                if (FORBIDDEN_PROPERTIES.has(declaration.prop)) {
                    problems.push(`${declaration.prop} on ${(declaration.parent as { selector?: string }).selector}`)
                }
            })

            root.walkAtRules('keyframes', (keyframes: AtRule) => {
                keyframes.walkDecls((declaration) => {
                    if (!COMPOSITED_PROPERTIES.has(declaration.prop)) {
                        problems.push(`@keyframes ${keyframes.params} animates ${declaration.prop}`)
                    }
                    if (CONTAINER_UNIT.test(declaration.value)) {
                        problems.push(`@keyframes ${keyframes.params} reads a container unit`)
                    }
                    if (looping.has(keyframes.params) && declaration.value.includes('var(')) {
                        problems.push(`@keyframes ${keyframes.params} loops and reads a var()`)
                    }
                })
            })

            expect(problems).toEqual([])
        }
    )
})
