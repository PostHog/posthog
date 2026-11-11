import { SignalReportArtefact } from '../types'
import { latestImplementationRunRef } from './latestImplementationRun'

function taskRun(
    id: string,
    createdAt: string,
    type: string,
    runId: string | null = `run-${id}`
): SignalReportArtefact {
    return {
        id,
        type: 'task_run',
        created_at: createdAt,
        content: { task_id: `task-${id}`, run_id: runId, product: 'signals', type },
    }
}

describe('latestImplementationRunRef', () => {
    it.each([
        ['no runs', [], null],
        ['only a research run', [taskRun('a', '2026-06-11T10:00:00Z', 'research')], null],
        [
            'the newest implementation run',
            [
                taskRun('a', '2026-06-11T10:00:00Z', 'implementation'),
                taskRun('b', '2026-06-11T12:00:00Z', 'implementation'),
                taskRun('c', '2026-06-11T13:00:00Z', 'research'),
            ],
            { taskId: 'task-b', runId: 'run-b' },
        ],
        ['an implementation run with no run id', [taskRun('a', '2026-06-11T10:00:00Z', 'implementation', null)], null],
    ])('finds %s', (_name, artefacts, expected) => {
        expect(latestImplementationRunRef(artefacts)).toEqual(expected)
    })
})
