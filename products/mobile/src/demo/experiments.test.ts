import {
    DEMO_EXPERIMENT_CHECKOUT,
    DEMO_EXPERIMENT_ONBOARDING,
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

    test.each([false, true])('shipping preserves saved conclusion fields unless replaced: %s', async (replace) => {
        await settle(
            demoExperimentsSource.endExperiment(DEMO_EXPERIMENT_CHECKOUT, {
                conclusion: 'won',
                conclusion_comment: 'The new checkout performed better.',
            })
        )
        const result = await settle(
            demoExperimentsSource.shipVariant(DEMO_EXPERIMENT_CHECKOUT, {
                variant_key: 'start-trial',
                ...(replace ? { conclusion: 'inconclusive' as const, conclusion_comment: '' } : {}),
            })
        )
        expect(result.status === 'shipped' && result.experiment).toMatchObject({
            conclusion: replace ? 'inconclusive' : 'won',
            conclusion_comment: replace ? '' : 'The new checkout performed better.',
        })
    })

    test('the demo sample ratio uses expected exposure counts', async () => {
        const experiment = await settle(demoExperimentsSource.fetchExperiment(DEMO_EXPERIMENT_ONBOARDING))
        const exposures = await settle(demoExperimentsSource.fetchExposures(experiment))
        const total = Object.values(exposures.total_exposures).reduce((sum, count) => sum + count, 0)
        expect(total).toBeGreaterThan(0)
        expect(exposures.sample_ratio_mismatch?.expected).toEqual({ control: total / 2, 'checklist-v2': total / 2 })
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
