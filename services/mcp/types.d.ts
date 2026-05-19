// ioredis v4 ships without bundled type declarations. We only use the default
// export (constructor) — typed loosely as `any` so TS can still check call sites
// that interact with it via the local `RedisLike` interface.
declare module 'ioredis' {
    const Redis: any
    export default Redis
}
