import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'

import { Logo } from '@posthog/brand/logo'
import { DOMParser, XMLSerializer } from '@xmldom/xmldom'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const root = new URL('../', import.meta.url)
const parts = ['blue', 'red', 'yellow', 'head']

function renderLogo(Component, dark, width, height) {
    const treatment = dark ? { variant: 'mono', color: '#fff' } : {}
    const markup = renderToStaticMarkup(createElement(Component, { ...treatment, width, height }))
    const { documentElement: svg } = new DOMParser().parseFromString(markup, 'image/svg+xml')
    svg.removeAttribute('aria-hidden')
    if (dark) {
        for (const element of Array.from(svg.getElementsByTagName('*'))) {
            if (element.getAttribute('fill') === 'currentColor') {
                element.setAttribute('fill', treatment.color)
            }
        }
    }
    return svg
}

function serialize(svg) {
    return new XMLSerializer().serializeToString(svg)
}

function renderLogos(dark) {
    const logomark = renderLogo(Logo.Logomark, dark, 52, 28)
    const layers = Array.from(logomark.getElementsByTagName('g')).filter((group) =>
        group.hasAttribute('data-logo-part')
    )
    if (layers.map((layer) => layer.getAttribute('data-logo-part')).join() !== parts.join()) {
        throw new Error('The brand logomark layers changed. Update the mobile animation to match.')
    }
    return {
        landscape: serialize(renderLogo(Logo, dark, 160, 28)),
        logomark: serialize(logomark),
        parts: Object.fromEntries(
            parts.map((part) => {
                const layerSvg = logomark.cloneNode(true)
                for (const group of Array.from(layerSvg.getElementsByTagName('g'))) {
                    if (group.hasAttribute('data-logo-part') && group.getAttribute('data-logo-part') !== part) {
                        group.parentNode.removeChild(group)
                    }
                }
                return [part, serialize(layerSvg)]
            })
        ),
    }
}

function writePng(relativePath, svg) {
    writeFileSync(new URL(relativePath, root), execFileSync('rsvg-convert', { input: serialize(svg) }))
}

switch (process.argv[2]) {
    case 'app': {
        const logos = { light: renderLogos(false), dark: renderLogos(true) }
        writeFileSync(new URL('src/ui/icons/brandLogos.json', root), `${JSON.stringify(logos, null, 4)}\n`)
        writePng('assets/splash-icon-dark.png', renderLogo(Logo.Logomark, true, 1040, 560))
        break
    }
    case 'icon': {
        const svg = renderLogo(Logo.Logomark, true, 1024, 1024)
        svg.setAttribute('viewBox', '-6.5 -18.5 65 65')
        writePng('assets/app.icon/Assets/logo-dark.png', svg)
        break
    }
    default:
        throw new Error('Usage: pnpm brand:generate app|icon')
}
