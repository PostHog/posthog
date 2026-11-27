import './AdventHoverSnow.scss'

const FLAKE_COUNT = 48
const CLEARANCE_PX = 6

let layer: HTMLDivElement | null = null

function createFlake(index: number): HTMLSpanElement {
    const flake = document.createElement('span')
    flake.className = 'AdventHoverSnow__flake'
    flake.style.left = `${(index * 37) % 100}%`
    flake.style.setProperty('--advent-flake-size', `${8 + ((index * 7) % 9)}px`)
    flake.style.setProperty('--advent-flake-duration', `${7 + ((index * 13) % 7)}s`)
    flake.style.setProperty('--advent-flake-delay', `-${(index * 5) % 13}s`)
    flake.style.setProperty('--advent-flake-drift', `${(((index * 11) % 7) - 3) * 12}px`)
    return flake
}

function createLayer(): HTMLDivElement {
    const element = document.createElement('div')
    element.className = 'AdventHoverSnow'
    element.setAttribute('aria-hidden', 'true')
    element.dataset.attr = 'advent-hover-snow'
    element.append(...Array.from({ length: FLAKE_COUNT }, (_, index) => createFlake(index)))
    return element
}

function mountHiddenSoItFadesIn(element: HTMLDivElement): void {
    document.body.append(element)
    element.getBoundingClientRect()
}

export function showAdventHoverSnow(trigger: DOMRect): void {
    layer ??= createLayer()
    layer.style.setProperty('--advent-clear-x', `${trigger.left - CLEARANCE_PX}px`)
    layer.style.setProperty('--advent-clear-y', `${trigger.top - CLEARANCE_PX}px`)
    layer.style.setProperty('--advent-clear-width', `${trigger.width + 2 * CLEARANCE_PX}px`)
    layer.style.setProperty('--advent-clear-height', `${trigger.height + 2 * CLEARANCE_PX}px`)
    if (!layer.isConnected) {
        mountHiddenSoItFadesIn(layer)
    }
    layer.classList.add('AdventHoverSnow--falling')
}

export function hideAdventHoverSnow(): void {
    layer?.classList.remove('AdventHoverSnow--falling')
}
