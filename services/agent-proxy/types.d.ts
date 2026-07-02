// ioredis v4 ships without bundled type declarations. We expose a minimal
// structural type so `import type { Redis } from 'ioredis'` resolves across
// all modules. Return types on Redis commands are typed as `any` — this lets
// the pre-existing call sites in redis-stream.ts use their own local type
// assertions (e.g. `raw as Array<[string, ...]>`) without conflicting with a
// stricter shim return type. Mirrors the pattern in services/mcp/types.d.ts.
declare module 'ioredis' {
    interface Pipeline {
        xadd(...args: any[]): this
        expire(...args: any[]): this
        set(...args: any[]): this
        exec(): Promise<Array<[Error | null, any]> | null>
    }

    interface Redis {
        connect(): Promise<void>
        quit(): Promise<string>
        // ioredis v4 disconnect() is synchronous and returns void (not a Promise).
        disconnect(): void
        duplicate(): Redis
        on(event: string, listener: (...args: any[]) => void): this
        get(key: string): Promise<string | null>
        set(key: string, value: string | number, ...args: any[]): Promise<any>
        exists(...keys: string[]): Promise<number>
        expire(key: string, seconds: number): Promise<number>
        del(...keys: string[]): Promise<number>
        xadd(key: string, ...args: any[]): Promise<string | null>
        xread(...args: any[]): Promise<any>
        xlen(key: string): Promise<number>
        xrange(key: string, start: string, end: string, ...args: any[]): Promise<any>
        xrevrange(key: string, end: string, start: string, ...args: any[]): Promise<any>
        watch(...keys: string[]): Promise<'OK'>
        unwatch(): Promise<'OK'>
        multi(): Pipeline
        status: string
    }

    const Redis: {
        new (url: string, opts?: any): Redis
        new (opts?: any): Redis
    }

    export { Redis }
    export default Redis
}

// CryptoKey is a WebCrypto global (lib.dom.d.ts). Node's `node:crypto` module
// also surfaces it at runtime but the @types/node declaration omits the re-export.
// Augment the ambient `crypto` module so `import type { CryptoKey } from 'crypto'`
// in ingest-handler.ts resolves to the same global type.
declare module 'crypto' {
    type CryptoKey = globalThis.CryptoKey
    export { CryptoKey }
}
