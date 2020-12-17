// Adapted from https://github.com/stipsan/ioredis-mock/issues/568#issuecomment-492558489
export const redisFactory = (): any => {
    const Redis = require('ioredis-mock')
    if (typeof Redis === 'object') {
        // the first mock is an ioredis shim because ioredis-mock depends on it
        // https://github.com/stipsan/ioredis-mock/blob/2ba837f07c0723cde993fb8f791a5fcfdabce719/src/index.js#L100-L109
        return {
            Command: { _transformer: { argument: {}, reply: {} } },
        }
    }
    // second mock for our code
    return function (...args: any[]) {
        const redis = new Redis(args)
        // adapted from copy/paste - our own brpop function!
        redis.brpop = async (...args: any[]) => {
            args.pop()
            return [args[0], await redis.rpop(...args)]
        }
        return redis
    }
}
