import { TaskRunArtifactResponseApi } from '../generated/api.schemas'
import { taskFiles } from './taskFiles'

function artifact(name: string, overrides: Partial<TaskRunArtifactResponseApi> = {}): TaskRunArtifactResponseApi {
    return {
        id: `id-${name}-${overrides.uploaded_at ?? '1'}`,
        name,
        type: 'output',
        source: 'agent_output',
        storage_path: `tasks/artifacts/${name}`,
        uploaded_at: '2026-01-01T10:00:00Z',
        ...overrides,
    }
}

describe('taskFiles', () => {
    it.each([
        ['no artifacts', null, []],
        ['one agent file', [artifact('report.md')], ['report.md']],
        [
            'files the agent did not hand back',
            [
                artifact('plan.md', { type: 'plan' }),
                artifact('screenshot.png', { source: 'user_attachment' }),
                artifact('skill.zip', { type: 'skill_bundle' }),
                artifact('reference', { storage_path: undefined }),
                artifact('old.csv', { dismissed_at: '2026-01-02T00:00:00Z' }),
                artifact('Weekly signups', {
                    type: 'reference',
                    storage_path: undefined,
                    metadata: {
                        reference_type: 'posthog_object',
                        object_kind: 'insight',
                        object_id: 'abc123',
                        source_message_ids: ['message-1'],
                        occurrence_count: 1,
                    },
                }),
            ],
            [],
        ],
        [
            'versions of one file, newest file first',
            [
                artifact('summary.md', { uploaded_at: '2026-01-01T09:00:00Z' }),
                artifact('chart.html', { uploaded_at: '2026-01-01T10:00:00Z' }),
                artifact('summary.md', { uploaded_at: '2026-01-01T11:00:00Z' }),
            ],
            ['summary.md', 'chart.html'],
        ],
    ])('lists %s', (_, artifacts, expected) => {
        expect(taskFiles('task-1', { id: 'run-1', artifacts }).map(({ file }) => file.name)).toEqual(expected)
    })

    it('links a file to its session with the file selected', () => {
        expect(taskFiles('task-1', { id: 'run-1', artifacts: [artifact('q3 revenue.md')] })[0].url).toEqual(
            '/ai?task=task-1&artifact=q3%20revenue.md'
        )
    })
})
