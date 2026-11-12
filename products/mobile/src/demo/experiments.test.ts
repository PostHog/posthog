import {
    DEMO_EXPERIMENT_CHECKOUT,
    DEMO_EXPERIMENT_SIDEBAR,
    demoExperimentsSource,
    resetDemoExperiments,
} from './experiments'

describe('demo experiments', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        resetDemoExperiments()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    async function settle<T>(promise: Promise<T>): Promise<T> {
        await jest.advanceTimersByTimeAsync(1000)
        return promise
    }

    test('a demo ship ends the experiment, serves the variant to everyone and moves it to Done', async () => {
        const result = await settle(
            demoExperimentsSource.shipVariant(DEMO_EXPERIMENT_CHECKOUT, {
                variant_key: 'start-trial',
                conclusion: 'won',
                open_cleanup_pr: true,
            })
        )
        expect(result.status === 'shipped' && result.experiment.flag_cleanup_task_id).toBeTruthy()

        const running = await settle(demoExperimentsSource.fetchExperiments({ status: 'running' }))
        const done = await settle(demoExperimentsSource.fetchExperiments({ status: 'complete' }))
        expect(running.results.map((item) => item.id)).not.toContain(DEMO_EXPERIMENT_CHECKOUT)
        const shipped = done.results.find((item) => item.id === DEMO_EXPERIMENT_CHECKOUT)
        expect(shipped).toMatchObject({ status: 'stopped', conclusion: 'won' })
        expect(JSON.stringify(shipped?.feature_flag.filters)).toContain('"key":"start-trial","rollout_percentage":100')
    })

    test('a second demo refresh inside five minutes waits like the server', async () => {
        const first = await settle(demoExperimentsSource.startRecalculation(DEMO_EXPERIMENT_SIDEBAR))
        expect(first.run?.status).toBe('pending')
        await jest.advanceTimersByTimeAsync(10_000)

        const second = await settle(demoExperimentsSource.startRecalculation(DEMO_EXPERIMENT_SIDEBAR))
        expect(second.run).toBeNull()
        expect(second.retryAfterMs).toBeGreaterThan(0)
    })
})
