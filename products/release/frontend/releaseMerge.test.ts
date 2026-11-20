import { MergeCandidate, releaseToKeep } from './releaseMerge'

const candidate = (id: string, linked: number): MergeCandidate => ({ id, name: id, summary: '', linked })

describe('releaseToKeep', () => {
    it.each<[string, MergeCandidate[], string | null]>([
        ['keeps the release with the most linked items', [candidate('a', 1), candidate('b', 3)], 'b'],
        ['keeps the first release on a tie', [candidate('a', 2), candidate('b', 2)], 'a'],
        ['keeps nothing without candidates', [], null],
    ])('%s', (_name, candidates, expected) => {
        expect(releaseToKeep(candidates)).toBe(expected)
    })
})
