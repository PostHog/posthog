import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'

import {
    RunArtifact,
    artifactPreviewKind,
    collectRunArtifacts,
    groupArtifactVersions,
    parseCsv,
    visibleRunArtifacts,
} from './taskRunArtifacts'

function artifact(overrides: Partial<TaskRunArtifactResponseApi>): TaskRunArtifactResponseApi {
    return {
        id: 'a1',
        name: 'report.md',
        type: 'output',
        source: 'agent_output',
        storage_path: 'tasks/artifacts/a1',
        uploaded_at: '2026-09-28T18:00:00Z',
        ...overrides,
    }
}

describe('taskRunArtifacts', () => {
    test.each([
        [
            'plain rows',
            'a,b\n1,2\n',
            [
                ['a', 'b'],
                ['1', '2'],
            ],
        ],
        [
            'quoted comma and newline',
            'name,note\n"Ada","x, y\nz"\n',
            [
                ['name', 'note'],
                ['Ada', 'x, y\nz'],
            ],
        ],
        ['doubled quotes and CRLF', 'q\r\n"say ""hi"""\r\n', [['q'], ['say "hi"']]],
        ['blank lines and no trailing newline', 'a\n\n1', [['a'], ['1']]],
    ])('parseCsv handles %s', (_, text, expected) => {
        expect(parseCsv(text)).toEqual(expected)
    })

    test.each([
        ['the content type', { name: 'x', content_type: 'text/html; charset=utf-8' }, 'html'],
        [
            'the extension when the type is octet-stream',
            { name: 'chart.png', content_type: 'application/octet-stream' },
            'image',
        ],
        ['the extension with no type', { name: 'weeks.csv' }, 'csv'],
        ['a video by extension', { name: 'walkthrough.webm' }, 'video'],
        ['an unknown binary', { name: 'bundle.zip', content_type: 'application/zip' }, 'none'],
    ])('artifactPreviewKind reads %s', (_, overrides, expected) => {
        expect(artifactPreviewKind(artifact(overrides))).toBe(expected)
    })

    it('visibleRunArtifacts keeps only files the agent wrote', () => {
        const kept = artifact({ id: 'kept' })
        const artifacts = [
            kept,
            artifact({ id: 'attachment', source: 'user_attachment' }),
            artifact({ id: 'plan', type: 'plan' }),
            artifact({ id: 'dismissed', dismissed_at: '2026-09-28T19:00:00Z' }),
            artifact({ id: 'reference', storage_path: undefined }),
        ]
        expect(visibleRunArtifacts(artifacts)).toEqual([kept])
    })

    it('collectRunArtifacts keeps files from earlier runs of a resumed task', () => {
        const latest = { id: 'run-3', artifacts: [artifact({ id: 'chart', uploaded_at: '2026-09-30T19:00:00Z' })] }
        const earlier = {
            id: 'run-1',
            artifacts: [
                artifact({ id: 'report', uploaded_at: '2026-09-30T17:00:00Z' }),
                artifact({ id: 'chart', uploaded_at: '2026-09-30T18:00:00Z' }),
            ],
        }
        expect(
            collectRunArtifacts([latest, null, earlier]).map(({ id, runId, uploaded_at }) => ({
                id,
                runId,
                uploaded_at,
            }))
        ).toEqual([
            { id: 'chart', runId: 'run-3', uploaded_at: '2026-09-30T19:00:00Z' },
            { id: 'report', runId: 'run-1', uploaded_at: '2026-09-30T17:00:00Z' },
        ])
    })

    test.each([
        [
            'merges one name across runs, newest first',
            [
                { id: 'report-1', runId: 'run-1', name: 'report.md', uploaded_at: '2026-09-30T17:00:00Z' },
                { id: 'report-3', runId: 'run-2', name: 'report.md', uploaded_at: '2026-09-30T19:00:00Z' },
                { id: 'report-2', runId: 'run-1', name: 'report.md', uploaded_at: '2026-09-30T18:00:00Z' },
            ],
            [{ name: 'report.md', versionIds: ['report-3', 'report-2', 'report-1'], latestId: 'report-3' }],
        ],
        [
            'keeps different names apart, by latest upload',
            [
                { id: 'chart-1', runId: 'run-1', name: 'chart.svg', uploaded_at: '2026-09-30T18:30:00Z' },
                { id: 'report-2', runId: 'run-2', name: 'report.md', uploaded_at: '2026-09-30T19:00:00Z' },
                { id: 'report-1', runId: 'run-1', name: 'report.md', uploaded_at: '2026-09-30T17:00:00Z' },
            ],
            [
                { name: 'report.md', versionIds: ['report-2', 'report-1'], latestId: 'report-2' },
                { name: 'chart.svg', versionIds: ['chart-1'], latestId: 'chart-1' },
            ],
        ],
    ])('groupArtifactVersions %s', (_, versions, expected) => {
        const artifacts: RunArtifact[] = versions.map(({ runId, ...overrides }) => ({
            ...artifact(overrides),
            runId,
        }))
        expect(
            groupArtifactVersions(artifacts).map((file) => ({
                name: file.name,
                versionIds: file.versions.map(({ id }) => id),
                latestId: file.latest.id,
            }))
        ).toEqual(expected)
    })
})
