import { vi } from 'vitest'
import type { Request, Response, NextFunction } from 'express'
import type { Redis } from 'ioredis'

import type { Config } from '@/server/config'
import type { ScopedCache } from '@/lib/utils/cache/ScopedCache'
import type { State } from '@/tools/types'

export function createMockConfig(overrides: Partial<Config> = {}): Config {
    return {
        port: 8080,
        redisUrl: undefined,
        internalApiUrlUs: undefined,
        internalApiUrlEu: undefined,
        inkeepApiKey: undefined,
        ...overrides,
    }
}

export function createMockRedis(): Redis {
    return {
        get: vi.fn().mockResolvedValue(null),
        setex: vi.fn().mockResolvedValue('OK'),
        del: vi.fn().mockResolvedValue(1),
        keys: vi.fn().mockResolvedValue([]),
        ping: vi.fn().mockResolvedValue('PONG'),
        quit: vi.fn().mockResolvedValue('OK'),
        on: vi.fn().mockReturnThis(),
    } as unknown as Redis
}

export function createMockCache(): ScopedCache<State> {
    return {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
        delete: vi.fn().mockResolvedValue(undefined),
        clear: vi.fn().mockResolvedValue(undefined),
    } as unknown as ScopedCache<State>
}

export function createMockRequest(overrides: Partial<Request> = {}): Request {
    return {
        method: 'GET',
        url: '/',
        headers: {},
        body: {},
        ...overrides,
    } as Request
}

export function createMockResponse(): Response & { _status: number; _body: unknown; _headers: Record<string, string> } {
    const res = {
        _status: 200,
        _body: undefined as unknown,
        _headers: {} as Record<string, string>,
        status(code: number) {
            this._status = code
            return this
        },
        send(body: unknown) {
            this._body = body
            return this
        },
        json(body: unknown) {
            this._body = body
            return this
        },
        set(key: string, value: string) {
            this._headers[key] = value
            return this
        },
        end(body?: unknown) {
            if (body !== undefined) {
                this._body = body
            }
            return this
        },
        statusCode: 200,
    }
    Object.defineProperty(res, 'statusCode', {
        get() {
            return this._status
        },
        set(value: number) {
            this._status = value
        },
    })
    return res as Response & { _status: number; _body: unknown; _headers: Record<string, string> }
}

export function createMockNext(): NextFunction {
    return vi.fn() as unknown as NextFunction
}

export function createMockApiClient(overrides: { meSuccess?: boolean; distinctId?: string } = {}) {
    const { meSuccess = true, distinctId = 'test-distinct-id' } = overrides
    return {
        users: vi.fn().mockReturnValue({
            me: vi.fn().mockResolvedValue(
                meSuccess
                    ? { success: true, data: { distinct_id: distinctId } }
                    : { success: false, error: 'Unauthorized' }
            ),
        }),
    }
}
