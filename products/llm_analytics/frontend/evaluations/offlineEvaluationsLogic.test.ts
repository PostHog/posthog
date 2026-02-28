import { mapOfflineExperimentItems, mapOfflineExperiments } from './offlineEvaluationsLogic'

describe('offlineEvaluationsLogic mapping helpers', () => {
    it('maps experiment summaries and ignores rows missing experiment id', () => {
        const experiments = mapOfflineExperiments([
            ['exp-1', 'Daily benchmark', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', '12', '5', '3'],
            [null, 'Missing id', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', '10', '4', '2'],
        ])

        expect(experiments).toEqual([
            {
                experimentId: 'exp-1',
                experimentName: 'Daily benchmark',
                firstSeenAt: '2026-01-01T00:00:00Z',
                lastSeenAt: '2026-01-02T00:00:00Z',
                eventsCount: 12,
                itemsCount: 5,
                metricPairsCount: 3,
            },
        ])
    })

    it('groups experiment rows into item rows and dynamic metric columns', () => {
        const { items, metricColumns } = mapOfflineExperimentItems([
            [
                'item-1',
                'Item one',
                'Experiment one',
                'accuracy',
                '1',
                'ok',
                '0.75',
                '0',
                '1',
                'numeric',
                'The answer matches the expected output exactly.',
                'trace-1',
                null,
                null,
                'input one',
                'output one',
                'expected one',
                '2026-01-03T00:00:00Z',
            ],
            [
                'item-1',
                'Item one',
                'Experiment one',
                'toxicity',
                '2',
                'error',
                null,
                null,
                null,
                'numeric',
                'The model output contains disallowed language.',
                null,
                null,
                null,
                null,
                null,
                null,
                '2026-01-04T00:00:00Z',
            ],
            [
                'item-2',
                'Item two',
                'Experiment one',
                'accuracy',
                '1',
                'not_applicable',
                null,
                null,
                null,
                'binary',
                null,
                null,
                'dataset-1',
                'dataset-item-1',
                'input two',
                'output two',
                'expected two',
                '2026-01-05T00:00:00Z',
            ],
        ])

        expect(metricColumns).toEqual([
            {
                key: 'accuracy::1',
                metricName: 'accuracy',
                metricVersion: '1',
            },
            {
                key: 'toxicity::2',
                metricName: 'toxicity',
                metricVersion: '2',
            },
        ])

        expect(items).toHaveLength(2)
        expect(items[0]).toMatchObject({
            itemId: 'item-2',
            itemName: 'Item two',
            experimentName: 'Experiment one',
            datasetId: 'dataset-1',
            datasetItemId: 'dataset-item-1',
            input: 'input two',
            output: 'output two',
            expected: 'expected two',
            lastSeenAt: '2026-01-05T00:00:00Z',
        })

        expect(items[1]).toMatchObject({
            itemId: 'item-1',
            itemName: 'Item one',
            experimentName: 'Experiment one',
            traceId: 'trace-1',
            input: 'input one',
            output: 'output one',
            expected: 'expected one',
            lastSeenAt: '2026-01-04T00:00:00Z',
        })

        expect(items[1].metrics['accuracy::1']).toEqual({
            status: 'ok',
            score: 0.75,
            scoreMin: 0,
            scoreMax: 1,
            resultType: 'numeric',
            reasoning: 'The answer matches the expected output exactly.',
            traceId: 'trace-1',
        })

        expect(items[1].metrics['toxicity::2']).toEqual({
            status: 'error',
            score: null,
            scoreMin: null,
            scoreMax: null,
            resultType: 'numeric',
            reasoning: 'The model output contains disallowed language.',
            traceId: null,
        })
    })
})
