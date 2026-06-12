import { afterAll, beforeAll } from 'vitest'

// quill-charts measures axis labels via an offscreen canvas during render. Its
// text-measure util has an explicit SSR fallback (length-based estimate) when the
// 2D context is unavailable, but reaching it requires `document.createElement` to
// exist. Stub just that — inside beforeAll, so it appears only after module load:
// at import time `typeof document === 'undefined'` must hold for libraries in the
// quill chain to correctly take their SSR branch.
beforeAll(() => {
    ;(globalThis as { document?: unknown }).document = {
        createElement: () => ({ getContext: () => null }),
    }
})

afterAll(() => {
    delete (globalThis as { document?: unknown }).document
})
