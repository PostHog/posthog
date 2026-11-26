import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import {
    notebooksAppRefreshOutputsRetrieve,
    notebooksAppRefreshScheduleCreate,
    notebooksAppRefreshStatusRetrieve,
} from '../generated/api'
import type {
    NotebookAppRefreshOutputsApiOutputs,
    NotebookAppRefreshStatusApi,
    NotebookAppScheduleSettingsApi,
} from '../generated/api.schemas'

const intervals = [
    { label: 'Hourly', value: 60 },
    { label: 'Every 6 hours', value: 360 },
    { label: 'Daily', value: 1440 },
    { label: 'Weekly', value: 10080 },
]

const localDate = (value: string): string => dayjs(value).format('MMM D, YYYY HH:mm')

function PrivateCheckSettings({
    targets,
    selected,
    onChange,
}: {
    targets: NotebookAppRefreshStatusApi['check_targets']
    selected: string[]
    onChange: (selected: string[]) => void
}): JSX.Element | null {
    if (!targets?.length) {
        return null
    }
    return (
        <fieldset className="border rounded p-3 flex flex-col gap-2 w-full">
            <legend>Private runtime checks</legend>
            <p className="m-0 text-secondary">
                Choose up to three cells to run with your current access. History records the outcome and duration. Each
                viewer runs a cell in the app to see its output with their own access.
            </p>
            {targets.map((target) => {
                const checked = selected.includes(target.node_id)
                return (
                    <LemonCheckbox
                        key={target.node_id}
                        checked={checked}
                        label={target.title + ' · ' + target.kind}
                        disabledReason={!checked && selected.length >= 3 ? 'Choose up to three cells.' : undefined}
                        onChange={(next) =>
                            onChange(
                                next ? [...selected, target.node_id] : selected.filter((id) => id !== target.node_id)
                            )
                        }
                    />
                )
            })}
        </fieldset>
    )
}

function ScheduleSettings({
    status,
    onSave,
    busy,
}: {
    status: NotebookAppRefreshStatusApi
    onSave: (settings: NotebookAppScheduleSettingsApi) => void
    busy: boolean
}): JSX.Element {
    const [interval, setIntervalMinutes] = useState(status.interval_minutes ?? 1440)
    const [freshness, setFreshness] = useState<number | undefined>(status.freshness_minutes ?? 2880)
    const [selected, setSelected] = useState<string[]>(
        status.revision === status.published_revision ? (status.checked_node_ids ?? []) : []
    )
    const save = (enabled: boolean): void =>
        onSave({
            enabled,
            checked_node_ids: selected,
            revision: status.published_revision,
            interval_minutes: interval,
            freshness_minutes: freshness ?? interval,
        })
    return (
        <div className="flex flex-wrap gap-3 items-end">
            <PrivateCheckSettings targets={status.check_targets} selected={selected} onChange={setSelected} />
            <label className="flex flex-col gap-1">
                Refresh interval
                <LemonSelect
                    aria-label="Refresh interval"
                    value={interval}
                    options={intervals}
                    onChange={(value) => {
                        setIntervalMinutes(value)
                        setFreshness((current) => Math.max(current ?? value, value))
                    }}
                />
            </label>
            <label className="flex flex-col gap-1">
                Maximum result age (minutes)
                <LemonInput
                    type="number"
                    min={interval}
                    max={43200}
                    value={freshness}
                    onChange={setFreshness}
                    placeholder="2880"
                />
            </label>
            <LemonButton
                type="primary"
                loading={busy}
                data-attr="notebook-app-save-refresh-schedule"
                disabledReason={
                    freshness && freshness >= interval && freshness <= 43200
                        ? undefined
                        : 'Choose an age between the refresh interval and 30 days.'
                }
                onClick={() => save(true)}
            >
                Save schedule
            </LemonButton>
            {status.enabled && (
                <LemonButton
                    type="secondary"
                    disabled={busy}
                    onClick={() =>
                        onSave({
                            enabled: false,
                            revision: status.published_revision,
                        })
                    }
                >
                    Turn off
                </LemonButton>
            )}
        </div>
    )
}

function RefreshHistory({ status }: { status: NotebookAppRefreshStatusApi }): JSX.Element {
    return status.history.length ? (
        <div className="overflow-auto">
            <table className="w-full text-left">
                <thead>
                    <tr>
                        <th>Scheduled for</th>
                        <th>Release</th>
                        <th>Result</th>
                        <th>Details</th>
                        <th>Duration</th>
                    </tr>
                </thead>
                <tbody>
                    {status.history.map((run) => (
                        <tr key={run.due_at}>
                            <td>{localDate(run.due_at)}</td>
                            <td>{run.revision}</td>
                            <td className="capitalize">{run.status}</td>
                            <td>
                                {run.detail ||
                                    (run.finished_at
                                        ? `${pluralize(run.output_count, 'SQL output')} · ${pluralize(run.checked_count ?? 0, 'private check')}`
                                        : 'Waiting for refresh')}
                            </td>
                            <td>{run.duration_seconds != null ? Math.round(run.duration_seconds) + 's' : '—'}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    ) : (
        <p className="text-secondary m-0">No refresh runs yet.</p>
    )
}

export function RefreshDetails({
    status,
    onSave,
    busy,
    onReload,
}: {
    status: NotebookAppRefreshStatusApi
    busy: boolean
    onReload: () => void
    onSave?: (settings: NotebookAppScheduleSettingsApi) => void
}): JSX.Element {
    const hasChecks = !!status.checked_node_ids?.length
    const active = status.enabled && status.revision === status.published_revision
    const state = status.stale ? 'Stale' : status.last_success_at ? 'Fresh' : 'Waiting for first refresh'
    return (
        <details className="border rounded p-3 mb-3">
            <summary className="cursor-pointer">
                <strong>{hasChecks ? 'Scheduled refresh and runtime checks' : 'Scheduled SQL refresh'}</strong>
                <span className="ml-2">
                    <LemonTag type={active && status.stale ? 'warning' : 'default'}>
                        {active ? (hasChecks && state === 'Fresh' ? 'On schedule' : state) : 'Off'}
                    </LemonTag>
                </span>
            </summary>
            <div className="flex flex-col gap-3 mt-3">
                <p className="m-0">
                    Freshness applies to native SQL outputs that use the published inputs. Python, connected SQL,
                    widgets, and outputs that depend on them keep their published results.
                </p>
                {hasChecks && (
                    <p className="m-0">
                        {status.checked_node_ids.length} private runtime{' '}
                        {status.checked_node_ids.length === 1 ? 'check' : 'checks'} scheduled. To see a result, open its
                        cell in the published app and run it with your access.
                    </p>
                )}
                {onSave && (
                    <>
                        <p className="m-0">
                            Refresh the default SQL results for release {status.published_revision}. You’ll receive a
                            notification if a run fails or the results get too old.
                        </p>
                        <ScheduleSettings status={status} onSave={onSave} busy={busy} />
                    </>
                )}
                {status.revision !== undefined && status.revision !== status.published_revision && (
                    <LemonBanner type="warning">
                        The schedule belongs to release {status.revision}. Save a schedule for the current release to
                        refresh it.
                    </LemonBanner>
                )}
                <div className="flex flex-wrap gap-3 items-center text-secondary">
                    {status.last_success_at && <span>Last successful refresh {localDate(status.last_success_at)}</span>}
                    {active && status.next_due_at && <span>Next refresh {localDate(status.next_due_at)}</span>}
                    <LemonButton size="small" onClick={onReload}>
                        Check status
                    </LemonButton>
                </div>
                <strong>Refresh history</strong>
                <RefreshHistory status={status} />
            </div>
        </details>
    )
}

export function NotebookAppRefreshPanel({
    shortId,
    editable,
    revision,
    onOutputs,
}: {
    shortId: string
    editable?: boolean
    revision: number
    onOutputs?: (outputs: NotebookAppRefreshOutputsApiOutputs) => void
}): JSX.Element | null {
    const project = String(ApiConfig.getCurrentTeamId())
    const [status, setStatus] = useState<NotebookAppRefreshStatusApi | null>(null)
    const [reload, setReload] = useState(0)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState(false)
    useEffect(() => {
        const controller = new AbortController()
        const options = { signal: controller.signal }
        async function load(): Promise<void> {
            const next = await notebooksAppRefreshStatusRetrieve(project, shortId, options)
            if (controller.signal.aborted) {
                return
            }
            setStatus(next)
            setError(false)
            if (onOutputs && next.revision === revision && next.last_success_at) {
                const result = await notebooksAppRefreshOutputsRetrieve(project, shortId, options)
                if (!controller.signal.aborted && result.revision === revision) {
                    onOutputs(result.outputs)
                }
            }
        }
        void load().catch(() => {
            if (!controller.signal.aborted) {
                setError(true)
                onOutputs?.({})
            }
        })
        return () => controller.abort()
    }, [project, shortId, reload, revision, onOutputs])
    async function save(settings: NotebookAppScheduleSettingsApi): Promise<void> {
        setBusy(true)
        try {
            setStatus(await notebooksAppRefreshScheduleCreate(project, shortId, settings))
            setError(false)
        } catch {
            setError(true)
        } finally {
            setBusy(false)
        }
    }
    return (
        <>
            {error && (
                <LemonBanner
                    type="warning"
                    className="mb-3"
                    action={{ children: 'Retry', onClick: () => setReload(reload + 1) }}
                >
                    Could not update scheduled refresh. Check your access and the published release.
                </LemonBanner>
            )}
            {status && (editable || status.revision !== undefined) && (
                <RefreshDetails
                    key={status.published_revision}
                    status={status}
                    busy={busy}
                    onReload={() => setReload(reload + 1)}
                    onSave={editable ? save : undefined}
                />
            )}
        </>
    )
}
