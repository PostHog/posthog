import type {
    TaskRunArtifactResponseApi,
    TaskRunLivingArtifactResponseApi,
} from 'products/tasks/frontend/generated/api.schemas'

import {
    LIVE_OBJECT_KINDS,
    PRODUCT_OBJECT_EMBEDS,
    RunArtifact,
    artifactPreviewKind,
    collectRunArtifacts,
    groupArtifactVersions,
    livingArtifactFiles,
    livingArtifactsFromResponse,
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

    test.each(['experiment', 'survey'])('the %s kind from the object tag registry gets a product embed', (kind) => {
        expect(LIVE_OBJECT_KINDS.has(kind)).toBe(true)
        expect(PRODUCT_OBJECT_EMBEDS.get(kind)).toBeTruthy()
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
        expect(visibleRunArtifacts(artifacts)).toEqual([kept, insight])
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

    const slackFile = livingArtifact({
        id: 'doc-2',
        name: 'weeks.xlsx',
        adapter: 'slack_file',
        current_version: 1,
        versions: [{ version: 1, run_id: 'run-1', size: 2048, created_at: '2026-09-30T16:00:00Z' }],
    })
    test.each([
        ['the envelope the endpoint returns', { artifacts: [livingArtifact({}), slackFile] }],
        [
            'the array of envelopes the generated client types, with a repeated id',
            [{ artifacts: [livingArtifact({})] }, { artifacts: [livingArtifact({}), slackFile] }],
        ],
    ])('living documents read from %s', (_, response) => {
        const files = livingArtifactFiles(livingArtifactsFromResponse(response))
        // An uploaded `report.md` keys by its name, so a living document with that name must not take the same key.
        expect(
            files.map((file) => ({
                key: file.key,
                versions: file.versions.map(({ id, living }) => ({ id, text: living?.text })),
            }))
        ).toEqual([
            {
                key: 'living-doc-1',
                versions: [
                    { id: 'living-doc-1-v2', text: '# Final' },
                    { id: 'living-doc-1-v1', text: '# Draft' },
                ],
            },
            { key: 'living-doc-2', versions: [{ id: 'living-doc-2-v1', text: null }] },
        ])
        expect(artifactPreviewKind(files[1].latest)).toBe('none')
    })
})
