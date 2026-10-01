import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'

import { artifactPreviewKind, parseCsv, visibleRunArtifacts } from './taskRunArtifacts'

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
})
