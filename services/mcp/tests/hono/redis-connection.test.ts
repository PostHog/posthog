import type Redis from 'ioredis'
import { EventEmitter } from 'node:events'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { connectRedis } from '@/hono/redis-connection'

class RedisStub extends EventEmitter {
    connect = vi.fn<() => Promise<void>>()
    disconnect = vi.fn()
}

describe('Redis startup connection', () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it('waits for readiness after the initial connection closes', async () => {
        const redis = new RedisStub()
        redis.connect.mockRejectedValue(new Error('Connection is closed.'))
        const connected = vi.fn()
        const connection = connectRedis(redis as unknown as InstanceType<typeof Redis>, 1000).then(connected)
        await vi.advanceTimersByTimeAsync(500)
        expect(connected).not.toHaveBeenCalled()

        redis.emit('ready')
        await connection
        expect(connected).toHaveBeenCalledOnce()
        expect(redis.listenerCount('ready')).toBe(0)
        expect(vi.getTimerCount()).toBe(0)
    })

    it('stops reconnecting when startup times out', async () => {
        const redis = new RedisStub()
        redis.connect.mockRejectedValue(new Error('Connection is closed.'))
        const connection = connectRedis(redis as unknown as InstanceType<typeof Redis>, 1000)
        await Promise.all([
            expect(connection).rejects.toThrow('Redis did not become ready within 1000ms'),
            vi.advanceTimersByTimeAsync(1000),
        ])
        expect(redis.disconnect).toHaveBeenCalledOnce()
        expect(redis.listenerCount('ready')).toBe(0)
        expect(redis.listenerCount('end')).toBe(0)
        expect(vi.getTimerCount()).toBe(0)
    })

    it('fails immediately when Redis stops trying to connect', async () => {
        const redis = new RedisStub()
        redis.connect.mockRejectedValue(new Error('Connection is closed.'))
        const connection = connectRedis(redis as unknown as InstanceType<typeof Redis>, 1000)
        redis.emit('end')
        await expect(connection).rejects.toThrow('Redis connection ended before startup')
        expect(redis.listenerCount('ready')).toBe(0)
        expect(vi.getTimerCount()).toBe(0)
    })
})
