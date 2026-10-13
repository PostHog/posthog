import type {
    TaskRunArtifactResponseApi,
    TaskRunLivingArtifactResponseApi,
} from 'products/tasks/frontend/generated/api.schemas'

import {
    RunArtifact,
    artifactEditConflict,
    artifactPreviewKind,
    collectRunArtifacts,
    editableArtifactKind,
    groupArtifactVersions,
    livingArtifactFiles,
    listboxKeyTarget,
    parseCsv,
    visibleRunArtifacts,
} from './taskRunArtifacts'

function livingArtifact(overrides: Partial<TaskRunLivingArtifactResponseApi>): TaskRunLivingArtifactResponseApi {
    return {
        id: 'doc-1',
        task_id: 'task-1',
        run_id: 'run-1',
        team_id: 1,
        name: 'report.md',
        artifact_type: 'document',
        adapter: 'slack_canvas',
        status: 'active',
        location: {},
        metadata: {},
        current_version: 2,
        versions: [
            { version: 1, run_id: 'run-1', content: '# Draft', created_at: '2026-09-30T17:00:00Z' },
            { version: 2, run_id: 'run-2', content: '# Final', created_at: '2026-09-30T18:00:00Z' },
        ],
        updated_at: '2026-09-30T18:00:00Z',
        ...overrides,
    }
}

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

    test.each([
        ['ArrowDown', 1, 4, 2],
        ['ArrowDown', 3, 4, 3],
        ['ArrowUp', 2, 4, 1],
        ['ArrowUp', 0, 4, 0],
        ['Home', 2, 4, 0],
        ['End', 0, 4, 3],
        ['Enter', 1, 4, null],
        ['ArrowDown', 0, 0, null],
    ])('listboxKeyTarget moves %s from %i of %i to %p', (key, current, count, expected) => {
        expect(listboxKeyTarget(key, current, count)).toBe(expected)
    })

    it('visibleRunArtifacts keeps files the agent wrote and cited PostHog objects', () => {
        const kept = artifact({ id: 'kept' })
        const insight = artifact({
            id: 'phref_insight',
            type: 'reference',
            source: 'posthog_object',
            storage_path: undefined,
            metadata: {
                reference_type: 'posthog_object',
                object_kind: 'insight',
                object_id: 'aBc123',
                source_message_ids: ['m1'],
                occurrence_count: 1,
            },
        })
        const artifacts = [
            kept,
            insight,
            artifact({ id: 'attachment', source: 'user_attachment' }),
            artifact({ id: 'plan', type: 'plan' }),
            artifact({ id: 'dismissed', dismissed_at: '2026-09-28T19:00:00Z' }),
            artifact({ id: 'reference', storage_path: undefined }),
        ]
        const savedByUser = artifact({ id: 'saved-by-user', source: '', uploaded_by: 'user' })
        expect(visibleRunArtifacts([...artifacts, savedByUser])).toEqual([kept, insight, savedByUser])
    })

    test.each([
        ['markdown by content type', { content_type: 'text/markdown' }, 'markdown'],
        ['plain text by extension with no type', { name: 'notes.txt', content_type: undefined }, 'plain-text'],
        ['CSV as not editable', { name: 'weeks.csv', content_type: 'text/csv' }, null],
        ['JSON as not editable', { name: 'data.json', content_type: 'application/json' }, null],
    ])('editableArtifactKind reads %s', (_, overrides, expected) => {
        expect(editableArtifactKind({ ...artifact(overrides), runId: 'run-1' })).toBe(expected)
    })

    const base = artifact({ id: 'v1', uploaded_at: '2026-09-30T17:00:00Z' })
    test.each([
        ['no conflict when the base is still the latest', [{ id: 'run-1', artifacts: [base] }], null],
        [
            'a newer version from a later run',
            [
                { id: 'run-2', artifacts: [artifact({ id: 'v2', uploaded_at: '2026-09-30T18:00:00Z' })] },
                { id: 'run-1', artifacts: [base] },
            ],
            'newer-version',
        ],
        [
            'every version dismissed',
            [{ id: 'run-1', artifacts: [{ ...base, dismissed_at: '2026-09-30T18:00:00Z' }] }],
            'dismissed',
        ],
    ])('artifactEditConflict finds %s', (_, runs, expected) => {
        expect(artifactEditConflict(runs, 'report.md', 'v1')).toBe(expected)
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

    it('collectRunArtifacts applies dismissals over run manifests from before the change', () => {
        const run = {
            id: 'run-1',
            artifacts: [
                artifact({ id: 'dismissed-here' }),
                artifact({ id: 'restored-here', dismissed_at: '2026-09-28T19:00:00Z' }),
                artifact({ id: 'untouched' }),
            ],
        }
        expect(
            collectRunArtifacts([run], { 'dismissed-here': true, 'restored-here': false }).map(({ id }) => id)
        ).toEqual(['restored-here', 'untouched'])
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
        [
            'keeps two cited objects with one name apart',
            [
                {
                    id: 'phref_a',
                    runId: 'run-1',
                    name: 'Signups',
                    type: 'reference',
                    uploaded_at: '2026-09-30T18:00:00Z',
                },
                {
                    id: 'phref_b',
                    runId: 'run-1',
                    name: 'Signups',
                    type: 'reference',
                    uploaded_at: '2026-09-30T17:00:00Z',
                },
            ],
            [
                { name: 'Signups', versionIds: ['phref_a'], latestId: 'phref_a' },
                { name: 'Signups', versionIds: ['phref_b'], latestId: 'phref_b' },
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

    function slackFile(
        location: Record<string, unknown>,
        name = 'signups.png',
        contentType = 'image/png',
        size = 2048
    ): TaskRunLivingArtifactResponseApi {
        return livingArtifact({
            id: 'doc-2',
            name,
            adapter: 'slack_file',
            current_version: 1,
            versions: [
                {
                    version: 1,
                    run_id: 'run-1',
                    size,
                    content_type: contentType,
                    location,
                    created_at: '2026-09-30T16:00:00Z',
                },
            ],
        })
    }

    test('livingArtifactFiles keeps each document apart and lists its versions newest first', () => {
        const files = livingArtifactFiles([livingArtifact({}), slackFile({ storage_path: 'tasks/doc.v1.png' })])
        // An uploaded `report.md` keys by its name, so a living document with that name must not take the same key.
        expect(
            files.map((file) => ({
                key: file.key,
                versions: file.versions.map(({ id, living }) => ({
                    id,
                    version: living?.version,
                    text: living?.text,
                    stored: living?.stored,
                })),
            }))
        ).toEqual([
            {
                key: 'living-doc-1',
                versions: [
                    { id: 'living-doc-1-v2', version: 2, text: '# Final', stored: false },
                    { id: 'living-doc-1-v1', version: 1, text: '# Draft', stored: false },
                ],
            },
            {
                key: 'living-doc-2',
                versions: [{ id: 'living-doc-2-v1', version: 1, text: null, stored: true }],
            },
        ])
    })

    test.each([
        [
            'a stored Slack file image previews as an image',
            { storage_path: 'tasks/doc.v1.png' },
            'image.png',
            'image/png',
            'image',
        ],
        [
            'a stored Slack file video previews as a video',
            { storage_path: 'tasks/doc.v1.mp4' },
            'demo.mp4',
            'video/mp4',
            'video',
        ],
        [
            'a stored Slack file CSV has no inline preview',
            { storage_path: 'tasks/doc.v1.csv' },
            'weeks.csv',
            'text/csv',
            'none',
        ],
        ['a Slack file with no stored copy has no preview', {}, 'image.png', 'image/png', 'none'],
        [
            'a stored Slack file video over the preview limit only downloads',
            { storage_path: 'tasks/doc.v1.mp4' },
            'demo.mp4',
            'video/mp4',
            'none',
            30 * 1024 * 1024,
        ],
    ])('%s', (_, location, name, contentType, expected, size = 2048) => {
        const [file] = livingArtifactFiles([slackFile(location, name, contentType, size)])
        expect(artifactPreviewKind(file.latest)).toBe(expected)
    })
})
