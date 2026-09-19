import { render } from '@testing-library/react'

import { ExperimentRefreshResultsBoundary } from './ExperimentRefreshResultsBoundary'

describe('experiment results commit boundary', () => {
    it('observes only the mounted subtree and acknowledges the exact committed response', () => {
        const observe = jest.fn()
        const committed = jest.fn()
        const primary = { variant_results: [] }
        const exposures = { timeseries: [] }
        const ready = {
            attemptId: 'refresh-a',
            mode: 'per_metric' as const,
            primary: [primary],
            secondary: [],
            exposures,
        }
        const props = { ready, primary: [primary], secondary: [], exposures, blocked: false, observe, committed }
        const view = render(
            <ExperimentRefreshResultsBoundary {...props} primary={[{}]}>
                <div>Results</div>
            </ExperimentRefreshResultsBoundary>
        )
        expect(observe).toHaveBeenCalledWith(true)
        expect(committed).not.toHaveBeenCalled()
        view.rerender(
            <ExperimentRefreshResultsBoundary {...props}>
                <div>Results</div>
            </ExperimentRefreshResultsBoundary>
        )
        expect(committed).toHaveBeenCalledWith('refresh-a')
        view.unmount()
        expect(observe).toHaveBeenLastCalledWith(false)
    })

    it('does not acknowledge loading or removed result content', () => {
        const committed = jest.fn()
        const ready = { attemptId: 'refresh-a', mode: 'per_metric' as const, primary: [], secondary: [], exposures: {} }
        const view = render(
            <ExperimentRefreshResultsBoundary
                ready={ready}
                primary={[]}
                secondary={[]}
                exposures={ready.exposures}
                blocked
                observe={jest.fn()}
                committed={committed}
            >
                <div>Loading</div>
            </ExperimentRefreshResultsBoundary>
        )
        view.unmount()
        expect(committed).not.toHaveBeenCalled()
    })
})
