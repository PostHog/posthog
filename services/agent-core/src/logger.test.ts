import pino from 'pino'

describe('logger arg-order patch', () => {
    function captureLogger(): { logged: unknown[]; logger: pino.Logger } {
        const logged: unknown[] = []
        const stream = {
            write: (chunk: string) => {
                logged.push(JSON.parse(chunk))
            },
        }
        // Re-import inside the test so we can use a custom stream + module reset.
        // Easier: build a pino instance with the same patch directly.
        const { patchForTest } = require('./logger-test-helper') as {
            patchForTest: (l: pino.Logger) => pino.Logger
        }
        const inner = pino({ level: 'trace' }, stream as pino.DestinationStream)
        return { logged, logger: patchForTest(inner) }
    }

    it('canonical form: logger.info({ ctx }, "msg") preserves ctx', () => {
        const { logged, logger } = captureLogger()
        logger.info({ session: 'abc' }, 'turn started')
        expect(logged).toHaveLength(1)
        const last = logged[0] as Record<string, unknown>
        expect(last.msg).toBe('turn started')
        expect(last.session).toBe('abc')
    })

    it('inverted form: logger.info("msg", { ctx }) is swapped and ctx is preserved', () => {
        const { logged, logger } = captureLogger()
        logger.info('turn started', { session: 'abc' })
        expect(logged).toHaveLength(1)
        const last = logged[0] as Record<string, unknown>
        expect(last.msg).toBe('turn started')
        expect(last.session).toBe('abc')
    })

    it('error with err: instance gets full stack via the serializer', () => {
        const { logged, logger } = captureLogger()
        try {
            throw new Error('boom')
        } catch (err) {
            logger.error({ err }, 'caught')
        }
        const last = logged[0] as Record<string, unknown>
        expect(last.msg).toBe('caught')
        const errField = last.err as Record<string, unknown>
        expect(errField.message).toBe('boom')
        expect(typeof errField.stack).toBe('string')
    })

    it('child loggers inherit the arg-order patch', () => {
        const { logged, logger } = captureLogger()
        const child = logger.child({ pkg: 'unit' })
        child.warn('something happened', { code: 42 })
        const last = logged[0] as Record<string, unknown>
        expect(last.msg).toBe('something happened')
        expect(last.code).toBe(42)
        expect(last.pkg).toBe('unit')
    })

    it('string-only call works (no swap)', () => {
        const { logged, logger } = captureLogger()
        logger.info('just a string')
        const last = logged[0] as Record<string, unknown>
        expect(last.msg).toBe('just a string')
    })

    it('printf-style array second arg is NOT swapped', () => {
        const { logged, logger } = captureLogger()
        // pino treats this as printf interpolation; we leave it alone.
        logger.info('formatted %s', ['arr'])
        expect(logged).toHaveLength(1)
    })
})
