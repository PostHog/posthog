import fs from 'node:fs'

/**
 * Orval emits `export const fooDefault = null` + `.default(fooDefault)` for
 * serializer fields with `default=None`. Zod rejects `.default(null)` on typed
 * schemas. Replace with `.nullish().default(null)`.
 */
export function fixNullDefaults(filePath) {
    let content = fs.readFileSync(filePath, 'utf-8')

    const nullConsts = new Set()
    for (const match of content.matchAll(/export const (\w+Default)\s*=\s*null\s*;/g)) {
        nullConsts.add(match[1])
    }
    if (nullConsts.size === 0) {
        return
    }

    const namesPattern = [...nullConsts].map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
    const defaultRe = new RegExp('\\.default\\(\\s*(?:' + namesPattern + ')\\s*[,)]', 'g')
    const constRe = new RegExp('export const (?:' + namesPattern + ')\\s*=\\s*null\\s*;', 'g')
    content = content.replace(defaultRe, '.nullish().default(null)')
    content = content.replace(constRe, '')

    fs.writeFileSync(filePath, content)
}

/** Annotate top-level Zod schema exports for tree-shaking. */
export function annotatePureZodExports(filePath) {
    const content = fs.readFileSync(filePath, 'utf-8')
    const annotated = content.replace(/^(export const \w+ =) (zod[.\n])/gm, '$1 /* @__PURE__ */ $2')
    fs.writeFileSync(filePath, annotated)
}
