import { hashImageBytes, imageRef, isImageRef, parseImageRef } from '../src/content-ref.ts'

// CONTRACT: these golden vectors MUST match the producer's content-ref in nodejs (its
// image-scrub.test.ts asserts the same input -> hash/ref), or references written by the producer
// won't resolve to what this consumer indexes. Change both together.
const INPUT = 'posthog-image-scrub-contract-v1'
const HASH = 'q1YIODUgcFH6CgV1DOI4SU'

describe('content-ref', () => {
    it('hashes to the golden 22-char base64url content hash', () => {
        expect(hashImageBytes(Buffer.from(INPUT))).toBe(HASH)
    })

    it('builds the golden team-scoped reference', () => {
        expect(imageRef(42, HASH)).toBe(`image:42:${HASH}`)
    })

    it('round-trips ref -> parse', () => {
        const p = parseImageRef(imageRef(42, HASH))
        expect(p?.teamId).toBe(42)
        expect(p?.hash).toBe(HASH)
    })

    it('is team-scoped: same bytes in different teams get different refs, same hash (tenant isolation)', () => {
        const bytes = Buffer.from('logo-png-bytes')
        const a = imageRef(42, hashImageBytes(bytes))
        const b = imageRef(99, hashImageBytes(bytes))
        expect(a).not.toBe(b)
        expect(parseImageRef(a)?.hash).toBe(parseImageRef(b)?.hash)
    })

    it('accepts a reference and rejects a raw data URI', () => {
        expect(isImageRef(imageRef(7, hashImageBytes(Buffer.from('x'))))).toBe(true)
        expect(isImageRef('data:image/png;base64,iVBORw0KG')).toBe(false)
    })
})
