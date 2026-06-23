// Compare-against-previous series render at half opacity so they recede behind the current period.
export const COMPARE_PREVIOUS_DIM_OPACITY = 0.5

// Inlined hex math (mirrors `lib/utils` `hexToRGBA`) so this module stays free of `lib/`/`~/`/`scenes/`
// deps and compiles in the MCP Vite bundle, which only resolves `products/*` and `@posthog/*`. Returns
// the input unchanged if it isn't a 3/6/8-digit hex (callers always pass palette hexes).
export function dimHexColor(hex: string, alpha: number): string {
    let h = hex.replace(/^#/, '')
    if (h.length === 3 || h.length === 4) {
        h = h
            .split('')
            .map((char) => char + char)
            .join('')
    }
    if (h.length !== 6 && h.length !== 8) {
        return hex
    }
    const r = parseInt(h.slice(0, 2), 16)
    const g = parseInt(h.slice(2, 4), 16)
    const b = parseInt(h.slice(4, 6), 16)
    return `rgba(${r},${g},${b},${alpha})`
}
