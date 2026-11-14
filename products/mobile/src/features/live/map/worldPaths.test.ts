import { WORLD_PATHS } from './worldPaths'

describe('WORLD_PATHS', () => {
    test('holds every country the map colors, each as one absolute path', () => {
        const codes = Object.keys(WORLD_PATHS)
        expect(codes.length).toBeGreaterThan(200)
        expect(codes).toEqual(expect.arrayContaining(['US', 'GB', 'DE']))
        expect(codes.every((code) => /^[A-Z]{2}$/.test(code))).toBe(true)
        expect(Object.values(WORLD_PATHS).every((d) => d.startsWith('M'))).toBe(true)
    })
})
