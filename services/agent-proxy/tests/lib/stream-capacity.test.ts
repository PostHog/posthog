import { describe, expect, it } from 'vitest'

import { StreamCapacity } from '@/lib/stream-capacity.js'

describe('StreamCapacity', () => {
    it('acquires until the pod-wide cap and rejects with pod_capacity beyond it', () => {
        const capacity = new StreamCapacity(2, 10)

        expect(capacity.tryAcquire('run-a')).toBeNull()
        expect(capacity.tryAcquire('run-b')).toBeNull()
        expect(capacity.tryAcquire('run-c')).toBe('pod_capacity')
        expect(capacity.openTotal).toBe(2)
    })

    it('rejects with run_capacity when one run reaches its fanout cap', () => {
        const capacity = new StreamCapacity(10, 2)

        expect(capacity.tryAcquire('run-a')).toBeNull()
        expect(capacity.tryAcquire('run-a')).toBeNull()
        expect(capacity.tryAcquire('run-a')).toBe('run_capacity')
        // Other runs are unaffected by run-a hitting its cap.
        expect(capacity.tryAcquire('run-b')).toBeNull()
    })

    it('release frees both the pod-wide and per-run slot', () => {
        const capacity = new StreamCapacity(1, 1)

        expect(capacity.tryAcquire('run-a')).toBeNull()
        expect(capacity.tryAcquire('run-a')).toBe('pod_capacity')

        capacity.release('run-a')

        expect(capacity.openTotal).toBe(0)
        expect(capacity.tryAcquire('run-a')).toBeNull()
    })

    it('interleaved acquire and release across runs keeps counts consistent', () => {
        const capacity = new StreamCapacity(3, 2)

        expect(capacity.tryAcquire('run-a')).toBeNull()
        expect(capacity.tryAcquire('run-a')).toBeNull()
        expect(capacity.tryAcquire('run-b')).toBeNull()
        expect(capacity.tryAcquire('run-b')).toBe('pod_capacity')

        capacity.release('run-a')
        expect(capacity.tryAcquire('run-b')).toBeNull()
        expect(capacity.tryAcquire('run-a')).toBe('pod_capacity')

        capacity.release('run-a')
        capacity.release('run-b')
        capacity.release('run-b')
        expect(capacity.openTotal).toBe(0)
    })

    it('release on an untracked run never goes negative', () => {
        const capacity = new StreamCapacity(1, 1)

        capacity.release('run-never-acquired')

        expect(capacity.openTotal).toBe(0)
        expect(capacity.tryAcquire('run-a')).toBeNull()
    })
})
