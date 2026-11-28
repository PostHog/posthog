jest.unmock('lib/utils/concurrencyController')

import { waitFor } from '@testing-library/react'
import { decodeParams } from 'kea-router'

import api from 'lib/api'
import { promiseResolveReject } from 'lib/utils/async'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import { useMocks } from '~/mocks/jest'
import * as queryRunner from '~/queries/query'
import { HogQLQueryResponse, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as notebookApi from '../generated/api'
import { emptyAppLayout } from './notebookAppLayout'
import { restorePublishedResults, savedQueryResult } from './notebookAppPublishedResults'
import { notebookAppViewerLogic } from './notebookAppViewerLogic'
import { notebookAppViewLink, restoreAppInputs } from './notebookAppViewLink'

describe('published viewer refreshes', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => jest.restoreAllMocks())

    it('applies a list for this viewer and recognizes the published defaults when reselected', async () => {
        const regions = { name: 'regions', type: 'list', value: ['North'] }
        jest.spyOn(notebookApi, 'notebooksAppReleaseRetrieve').mockResolvedValue({
            revision: 2,
            title: 'Regions',
            markdown: '',
            layout: {
                ...emptyAppLayout(),
                blocks: [
                    { id: 'regions', kind: 'input', tab_id: 'overview', variable: 'regions', input_kind: 'select' },
                ],
            },
            variables: [regions],
            has_previous: false,
            results_as_of: null,
            published_at: null,
        })
        const requests: unknown[] = []
        useMocks({
            post: {
                '/api/projects/1/notebooks/report/app_queries/': async ({ request }) => {
                    requests.push(await request.json())
                    return [200, []]
                },
            },
        })
        const viewer = notebookAppViewerLogic({ project: '1', shortId: 'report', sessionId: 'viewer' })
        viewer.mount()
        try {
            await waitFor(() => expect(viewer.values.variables).toEqual([regions]))
            expect(viewer.values.dirty).toBe(false)
            viewer.actions.setAuto(false)
            viewer.actions.changeInput('regions', ['North', 'South'])
            expect(viewer.values.dirty).toBe(true)
            viewer.actions.changeInput('regions', ['North'])
            expect(viewer.values.dirty).toBe(false)
            viewer.actions.changeInput('regions', [])
            viewer.actions.refresh()
            await waitFor(() => expect(viewer.values.results?.variables).toEqual([{ ...regions, value: [] }]))
            expect(requests).toEqual([{ revision: 2, variables: [{ ...regions, value: [] }] }])
        } finally {
            viewer.unmount()
        }
    })

    it('opens a link in the original project and runs only exposed, compatible inputs for the new viewer', async () => {
        const defaults = [
            { name: 'regions', type: 'list', value: ['North'] },
            { name: 'days', type: 'number', value: 7 },
            { name: 'hidden', type: 'boolean', value: true },
        ]
        const url = new URL(
            notebookAppViewLink('42', 'report', 'details', [{ name: 'regions', type: 'list', value: ['R&D', 'A+B'] }])
        )
        expect(url.pathname + url.search).toBe('/project/42/notebooks/report?view=app')
        const { appView } = decodeParams(url.hash, '#')
        expect(appView.tab).toBe('details')
        const inputs = { ...appView.inputs, days: 'old type', hidden: false }
        const viewer = notebookAppViewerLogic({
            project: '42',
            shortId: 'report',
            sessionId: 'linked',
            initialInputs: inputs,
        })
        jest.spyOn(notebookApi, 'notebooksAppReleaseRetrieve').mockResolvedValue({
            revision: 2,
            title: 'Regions',
            markdown: '',
            has_previous: false,
            published_at: null,
            results_as_of: null,
            layout: {
                ...emptyAppLayout(),
                blocks: defaults.slice(0, 2).map(({ name }) => ({
                    id: name,
                    kind: 'input',
                    tab_id: 'overview',
                    variable: name,
                })),
            },
            variables: defaults,
        })
        const plan = jest.spyOn(notebookApi, 'notebooksAppQueriesCreate').mockResolvedValue([])
        viewer.mount()
        try {
            await waitFor(() =>
                expect(viewer.values.results?.variables).toEqual([
                    { ...defaults[0], value: ['R&D', 'A+B'] },
                    defaults[1],
                ])
            )
            expect(plan).toHaveBeenCalledTimes(1)
        } finally {
            viewer.unmount()
        }
    })

    it('bounds simultaneous queries, commits their results together, and cancels only the superseded viewer queries', async () => {
        const plans = Array.from({ length: 6 }, (_, i) => ({
            node_id: String(i),
            query: 'SELECT ' + i,
            matches_defaults: false,
        }))
        jest.spyOn(notebookApi, 'notebooksAppReleaseRetrieve').mockResolvedValue({
            revision: 1,
            title: 'Viewer test',
            markdown: '',
            layout: emptyAppLayout(),
            variables: [],
            has_previous: false,
            results_as_of: null,
            published_at: null,
        })
        jest.spyOn(notebookApi, 'notebooksAppQueriesCreate').mockResolvedValue(plans)
        const pending = new Map<string, { signal: AbortSignal; finish: () => void }>()
        jest.spyOn(queryRunner, 'performQuery').mockImplementation((query, options, _refresh, id) => {
            expect(query.tags?.productKey).toBe(ProductKey.NOTEBOOKS)
            const { promise, resolve, reject } = promiseResolveReject<HogQLQueryResponse>()
            pending.set(id!, { signal: options!.signal!, finish: () => resolve({ columns: ['n'], results: [[1]] }) })
            options!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {
                once: true,
            })
            return promise
        })
        const cancel = jest.spyOn(api, 'cancelQuery').mockResolvedValue(undefined)
        const viewer = { project: '1', shortId: 'shared' }
        const first = notebookAppViewerLogic({ ...viewer, sessionId: 'first' })
        const second = notebookAppViewerLogic({ ...viewer, sessionId: 'second' })
        first.mount()
        second.mount()
        try {
            await waitFor(() => expect(second.values.release).toBeTruthy())
            first.actions.refresh(true)
            await waitFor(() => expect(pending.size).toBe(4))
            const firstDone = Array.from(pending.keys())[0]
            pending.get(firstDone)!.finish()
            await waitFor(() => expect(pending.size).toBe(5))
            expect(first.values.results).toBeNull()
            const firstRunning = Array.from(pending.keys()).slice(1)
            second.actions.refresh(true)
            await waitFor(() => expect(pending.size).toBe(9))
            const secondRunning = Array.from(pending.keys()).slice(5)
            first.actions.refresh(true)
            await waitFor(() => expect(cancel).toHaveBeenCalledTimes(4))
            expect(cancel.mock.calls.map(([id]) => id).sort()).toEqual(firstRunning.sort())
            const secondSignal = pending.get(secondRunning[0])!.signal
            for (const id of secondRunning) {
                pending.get(id)!.finish()
            }
            const secondRequests = (): { signal: AbortSignal; finish: () => void }[] =>
                Array.from(pending.values()).filter((request) => request.signal === secondSignal)
            await waitFor(() => expect(secondRequests()).toHaveLength(6))
            expect(second.values.results).toBeNull()
            for (const request of secondRequests().slice(4)) {
                request.finish()
            }
            await waitFor(() => expect(Object.keys(second.values.results?.outputs ?? {})).toHaveLength(6))
            await waitFor(() => expect(pending.size).toBe(15))
        } finally {
            first.unmount()
            second.unmount()
        }
        expect(cancel.mock.calls).toHaveLength(8)
        expect(cancel.mock.calls.every(([id, project]) => id !== Array.from(pending.keys())[0] && project === 1)).toBe(
            true
        )
    })
})

it('restores the pinned run for connected SQL and distinguishes complete, partial and unauthorized results', async () => {
    const columns = ['n']
    const rows = Array.from({ length: 7 }, (_, i) => [i])
    const result = { status: 'ok', columns, first_page: rows.slice(0, 5), row_count: 7, has_more: true }
    const run = jest.spyOn(notebookApi, 'notebooksSqlV2RunsRetrieve')
    const viewer = { project: '1', shortId: 'report', sessionId: 'viewer' }
    const runId = '00000000-0000-4000-8000-000000000061'
    const attrs = { runId, connectionId: 'external', result: { ...result, previewOnly: true } }
    const release = {
        revision: 1,
        title: 'Saved SQL',
        markdown: `<SQLV2 nodeId="counts" runId="${runId}" connectionId="external" code="select 1" />`,
        layout: {
            ...emptyAppLayout(),
            blocks: [{ id: 'output', tab_id: 'overview', kind: 'cell' as const, node_id: 'counts' }],
        },
        variables: [],
        has_previous: false,
        results_as_of: null,
        published_at: null,
    }
    const controller = new AbortController()
    const read = async (): Promise<ReturnType<typeof savedQueryResult>> =>
        savedQueryResult(attrs, (await restorePublishedResults(viewer, release, controller)).counts)
    try {
        expect(savedQueryResult(attrs)).toBe('loading')
        run.mockResolvedValueOnce({ status: 'done', result, rows })
        expect(await read()).toMatchObject({ rows: 'complete', result: { results: rows } })
        expect(run).toHaveBeenCalledWith('1', 'report', runId, { node_id: 'counts' }, { signal: controller.signal })
        run.mockResolvedValueOnce({ status: 'done', result })
        expect(await read()).toMatchObject({ rows: 'partial', result: { results: rows.slice(0, 5) } })
        run.mockResolvedValueOnce({ status: 'done', result, rows: Array.from({ length: 300 }, (_, i) => [i]) })
        expect(await read()).toMatchObject({ rows: 'capped' })
        run.mockRejectedValueOnce(new Error('Permission denied'))
        expect(await read()).toBe('unavailable')
    } finally {
        run.mockRestore()
    }
})

it('restores compatible published input values at the same character and calendar bounds as the API', () => {
    const variables: NotebookVariable[] = [
        { name: 'names', type: 'list', value: [] },
        { name: 'start', type: 'date', value: null },
        { name: 'limit', type: 'number', value: 5 },
        { name: 'region', type: 'string', value: 'north' },
    ]
    const blocks = variables.map(({ name }) => ({
        id: name,
        kind: 'input' as const,
        variable: name,
        tab_id: 'overview',
        ...(name === 'limit' && { input_kind: 'slider' as const, min: 1, max: 9, step: 2 }),
        ...(name === 'region' && { input_kind: 'select' as const, options: ['north', 'south'] }),
    }))
    const names = ['🦔'.repeat(600), 'a'.repeat(400)]
    const inputs = { names, start: '2024-02-29 09:30:00Z', limit: 7, region: 'south' }
    expect(restoreAppInputs(variables, inputs, blocks).map((v) => v.value)).toEqual(Object.values(inputs))
    expect(
        restoreAppInputs(
            variables,
            { names: [...names, 'x'], start: '2026-02-30', limit: 6, region: 'unknown' },
            blocks
        )
    ).toEqual(variables)
})
