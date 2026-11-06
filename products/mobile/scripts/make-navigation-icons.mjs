import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = new URL('../', import.meta.url)
const icons = {
    home: ['HomeIcon', 24, 2],
    chats: ['SpacesIcon', 24, 2],
    views: ['ViewsIcon', 24, 2],
    errors: ['ErrorTriangleIcon', 24, 2],
    replay: ['RecordingIcon', 24, 2],
    compose: ['ComposeIcon', 24, 2],
    filter: ['FilterIcon', 22, 2],
    more: ['MoreIcon', 22, 0],
    back: ['ChevronLeftIcon', 20, 2],
    next: ['ChevronRightIcon', 20, 2],
    external: ['ExternalLinkIcon', 20, 2],
    close: ['CloseIcon', 20, 2.4],
    done: ['CheckIcon', 20, 2],
}
const destination = new URL('src/ui/icons/native/', root)
mkdirSync(destination, { recursive: true })
for (const [name, [component, size, stroke]] of Object.entries(icons)) {
    const source = readFileSync(new URL(`src/ui/icons/${component}.tsx`, root), 'utf8')
    const shapes = source.match(/<(?:Path|Rect|Circle)\b[^>]*?\/>/g)
    if (!shapes?.length) throw new Error(`No SVG geometry in ${component}`)
    const geometry = shapes
        .join('')
        .replace(/<(Path|Rect|Circle)/g, (_, tag) => `<${tag.toLowerCase()}`)
        .replace(/=\{([\d.]+)\}/g, '="$1"')
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="${size}" height="${size}" fill="${stroke ? 'none' : 'black'}" stroke="${stroke ? 'black' : 'none'}" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${geometry}</svg>`
    for (const scale of [1, 2, 3]) {
        const suffix = scale === 1 ? '' : `@${scale}x`
        execFileSync(
            'rsvg-convert',
            [
                '-w',
                String(size * scale),
                '-h',
                String(size * scale),
                '-o',
                fileURLToPath(new URL(`${name}${suffix}.png`, destination)),
            ],
            { input: svg }
        )
    }
}
