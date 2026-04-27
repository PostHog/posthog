import { describe, expect, it } from 'vitest'

import { SnippetRunner } from '../src/lib/runner'

interface FakeClient {
    sayHello(input: { name: string }): Promise<{ greeting: string }>
    bigList(): Promise<{ items: number[] }>
    boom(): Promise<never>
    fakeHttp(): Promise<never>
}

function makeClient(): FakeClient {
    return {
        async sayHello(input) {
            return { greeting: `hello ${input.name}` }
        },
        async bigList() {
            return { items: Array.from({ length: 1000 }, (_, i) => i) }
        },
        async boom() {
            throw new Error('kaboom')
        },
        async fakeHttp() {
            const err = new Error('Not Found') as Error & { status: number; body: unknown; kind: 'http' }
            err.status = 404
            err.body = { detail: 'no such resource' }
            err.kind = 'http'
            throw err
        },
    }
}

describe('SnippetRunner', () => {
    const runner = new SnippetRunner(() => makeClient())

    it('runs a snippet against the client and returns the value', async () => {
        const result = await runner.run({
            snippet: 'const r = await client.sayHello({ name: "world" }); return r.greeting',
        })
        expect(result.error).toBeUndefined()
        expect(result.value).toBe('hello world')
    })

    it('captures console.log into stdout', async () => {
        const result = await runner.run({
            snippet: 'console.log("hi"); return 1',
        })
        expect(result.stdout).toBe('hi')
        expect(result.value).toBe(1)
    })

    it('strips type annotations before exec', async () => {
        const result = await runner.run({
            snippet: 'const x: number = 42; const y = x as number; return y',
        })
        expect(result.error).toBeUndefined()
        expect(result.value).toBe(42)
    })

    it('classifies invalid TS as a syntax error', async () => {
        // ts.transpileModule is lenient — it tries hard to recover. Use input that
        // unambiguously fails the JS parser even after recovery (incomplete declaration).
        const result = await runner.run({
            snippet: 'const x =',
        })
        expect(result.error?.kind).toBe('syntax')
    })

    it('classifies thrown errors as runtime', async () => {
        const result = await runner.run({
            snippet: 'await client.boom()',
        })
        expect(result.error?.kind).toBe('runtime')
        expect(result.error?.message).toContain('kaboom')
    })

    it('classifies HTTP errors and includes status + body', async () => {
        const result = await runner.run({
            snippet: 'await client.fakeHttp()',
        })
        expect(result.error?.kind).toBe('http')
        const details = result.error?.details as { status?: number; body?: unknown }
        expect(details?.status).toBe(404)
        expect(details?.body).toEqual({ detail: 'no such resource' })
    })

    it('truncates oversized return values and emits a shape hint', async () => {
        const result = await runner.run({
            snippet: 'return await client.bigList()',
            maxBytes: 256,
        })
        expect(result.truncated).toBe(true)
        expect(result.shapeHint).toContain('items')
    })

    it('fires timeout', async () => {
        const result = await runner.run({
            snippet: 'await new Promise((r) => setTimeout(r, 5000))',
            timeoutMs: 100,
        })
        expect(result.error?.kind).toBe('runtime')
        expect(result.error?.message).toContain('timed out')
    })
})
