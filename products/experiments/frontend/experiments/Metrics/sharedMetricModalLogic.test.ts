import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { METRIC_CONTEXTS } from './experimentMetricModalLogic'
import { MODAL_PAGE_SIZE, sharedMetricModalLogic } from './sharedMetricModalLogic'

const metric = (id: number, kind: NodeKind = NodeKind.ExperimentMetric, tags: string[] = []): any => ({
    id,
    name: `metric ${id}`,
    query: { kind },
    tags,
})

describe('sharedMetricModalLogic', () => {
    let logic: ReturnType<typeof sharedMetricModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/experiment_saved_metrics': ({ request }) => {
                    const url = new URL(request.url)
                    const offset = parseInt(url.searchParams.get('offset') ?? '0')
                    const search = url.searchParams.get('search') ?? ''
                    if (search === 'nomatch') {
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    }
                    if (offset === 0) {
                        // metric 1 (kept) + metric 2 (incompatible kind, filtered out) on page 1
                        return [
                            200,
                            {
                                count: 3,
                                next: `http://localhost/api/projects/997/experiment_saved_metrics?limit=${MODAL_PAGE_SIZE}&offset=${MODAL_PAGE_SIZE}&search=${search}`,
                                previous: null,
                                results: [
                                    metric(1, NodeKind.ExperimentMetric, ['main']),
                                    metric(2, NodeKind.ExperimentTrendsQuery),
                                ],
                            },
                        ]
                    }
                    // metric 3 lives on the second page and carries a tag absent from page 1
                    return [
                        200,
                        {
                            count: 3,
                            next: null,
                            previous: null,
                            results: [metric(3, NodeKind.ExperimentMetric, ['secondary'])],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = sharedMetricModalLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('openSharedMetricModal resets search and requests page 1 with limit 20 offset 0', async () => {
        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('stale')
            logic.actions.openSharedMetricModal(METRIC_CONTEXTS.primary)
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ searchTerm: '' })
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining(`limit=${MODAL_PAGE_SIZE}`))
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('offset=0'))
    })

    it('loading eagerly pulls in every page so compatible metrics span all of them', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        })
            .toDispatchActions(['loadSharedMetricsSuccess', 'loadAllSharedMetrics', 'loadAllSharedMetricsSuccess'])
            .toMatchValues({
                // metric 2 (incompatible kind) is excluded; metric 3 comes from the second page
                compatibleSharedMetrics: [expect.objectContaining({ id: 1 }), expect.objectContaining({ id: 3 })],
                displayedMetrics: [expect.objectContaining({ id: 1 }), expect.objectContaining({ id: 3 })],
            })
    })

    it('availableTags covers tags from every page, not just the rendered one', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])
        // "secondary" only exists on the second page, which the eager load brought in
        await expectLogic(logic).toMatchValues({ availableTags: ['main', 'secondary'] })
    })

    it('selectByTag selects a tag-matching metric from a page that was not first rendered', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])

        // "secondary" only lives on the second page, which was loaded eagerly
        await expectLogic(logic, () => {
            logic.actions.selectByTag('secondary', [])
        }).toMatchValues({
            filterTags: ['secondary'],
            selectedMetricIds: [3],
            displayedMetrics: [expect.objectContaining({ id: 3 })],
        })
    })

    it('tags are additive — clicking multiple tags accumulates the selection', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.selectByTag('main', [])
        }).toMatchValues({ filterTags: ['main'], selectedMetricIds: [1] })

        // a second tag adds to the selection rather than replacing it
        await expectLogic(logic, () => {
            logic.actions.selectByTag('secondary', [])
        }).toMatchValues({
            filterTags: ['main', 'secondary'],
            selectedMetricIds: [1, 3],
        })
    })

    it('clicking an active tag again deselects only that tag’s metrics', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])

        logic.actions.selectByTag('main', [])
        await expectLogic(logic, () => {
            logic.actions.selectByTag('secondary', [])
        }).toMatchValues({ selectedMetricIds: [1, 3] })

        // toggling "main" back off removes metric 1 but leaves metric 3 (still under "secondary")
        await expectLogic(logic, () => {
            logic.actions.selectByTag('main', [])
        }).toMatchValues({
            filterTags: ['secondary'],
            selectedMetricIds: [3],
        })
    })

    it('a metric covered by another active tag stays selected when one tag is toggled off', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/experiment_saved_metrics': ({ request }) => {
                    const offset = parseInt(new URL(request.url).searchParams.get('offset') ?? '0')
                    if (offset === 0) {
                        return [
                            200,
                            {
                                count: 2,
                                next: `http://localhost/api/projects/997/experiment_saved_metrics?limit=${MODAL_PAGE_SIZE}&offset=${MODAL_PAGE_SIZE}`,
                                previous: null,
                                results: [metric(1, NodeKind.ExperimentMetric, ['main', 'shared'])],
                            },
                        ]
                    }
                    return [
                        200,
                        {
                            count: 2,
                            next: null,
                            previous: null,
                            results: [metric(3, NodeKind.ExperimentMetric, ['secondary', 'shared'])],
                        },
                    ]
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])

        logic.actions.selectByTag('shared', []) // selects metrics 1 and 3 (both carry "shared")
        await expectLogic(logic, () => {
            logic.actions.selectByTag('main', []) // metric 1 also carries "main"
        }).toMatchValues({ selectedMetricIds: [1, 3] })

        // toggling "shared" off: metric 1 stays (still under "main"), metric 3 drops
        await expectLogic(logic, () => {
            logic.actions.selectByTag('shared', [])
        }).toMatchValues({
            filterTags: ['main'],
            selectedMetricIds: [1],
        })
    })

    it('selectByTag excludes already-added metrics from the selection', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])

        // metric 1 carries "main" but is already on the experiment, so it must not be selected
        await expectLogic(logic, () => {
            logic.actions.selectByTag('main', [1])
        }).toMatchValues({
            filterTags: ['main'],
            selectedMetricIds: [],
        })
    })

    it('setSearchTerm reloads with the search term and clears any active tag filter', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])
        logic.actions.selectByTag('main', [])

        jest.spyOn(api, 'get')
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('revenue')
        }).toDispatchActions(['loadAllSharedMetricsSuccess'])
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=revenue'))
        await expectLogic(logic).toMatchValues({
            filterTags: [],
            compatibleSharedMetrics: [expect.objectContaining({ id: 1 }), expect.objectContaining({ id: 3 })],
        })
    })

    it('toggleSelectedMetricId adds then removes a metric id', async () => {
        await expectLogic(logic, () => {
            logic.actions.toggleSelectedMetricId(5)
        }).toMatchValues({ selectedMetricIds: [5] })
        await expectLogic(logic, () => {
            logic.actions.toggleSelectedMetricId(5)
        }).toMatchValues({ selectedMetricIds: [] })
    })

    it('tracks hasAnyCompatibleSharedMetrics from the unfiltered baseline, not the current search', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ hasAnyCompatibleSharedMetrics: true })

        // a search that returns zero must NOT flip the baseline to false
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('nomatch')
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            compatibleSharedMetrics: [],
            hasAnyCompatibleSharedMetrics: true,
        })
    })

    it('hasAnyCompatibleSharedMetrics is false when the unfiltered load has no compatible metrics', async () => {
        // mount with a fresh mock where the baseline genuinely has none
        useMocks({
            get: {
                '/api/projects/:team_id/experiment_saved_metrics': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadSharedMetrics()
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ hasAnyCompatibleSharedMetrics: false })
    })
})
