import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonCollapse, LemonDialog, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
    SignalScoutPrecheckTestApi,
} from 'products/signals/frontend/generated/api.schemas'

import type { ScoutSurface } from '../../../inboxAnalytics'
import { scoutPrecheckLogic } from '../../../logics/scoutPrecheckLogic'

const QUERY_PLACEHOLDER = `SELECT count()
FROM events
WHERE event = '$exception' AND timestamp > {since}`

function testVerdict(result: SignalScoutPrecheckTestApi): string {
    switch (result.reason) {
        case 'no_rows':
            return 'The next scheduled run skips. The query found no rows.'
        case 'rows':
            return `The next scheduled run starts. The query found ${result.row_count} ${result.row_count === 1 ? 'row' : 'rows'}.`
        case 'false_value':
            return 'The next scheduled run skips. The query returned a single false value, such as a count of 0.'
        case 'query_error':
            return 'The next scheduled run starts, because a query that fails never skips a run.'
    }
}

/**
 * The pre-check of one scout in its settings form: a HogQL query that a scheduled run checks
 * before it starts. No rows, or a single false value, skips the run, so a scout that watches a quiet
 * surface costs nothing between bursts.
 *
 * The query does not save on change, like the record schema. A half-typed query would fail on the
 * next tick, so the editor stages a draft, the test button tries it, and the save button commits it.
 */
export function ScoutPrecheckSection({
    config,
    onUpdate,
    updating = false,
    surface,
    onUnsavedChange,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
    surface: ScoutSurface
    /** Called when the editor gains or loses an unsaved edit, so a host modal can guard its backdrop. */
    onUnsavedChange?: (unsaved: boolean) => void
}): JSX.Element {
    const logic = scoutPrecheckLogic({ configId: config.id, skillName: config.skill_name, surface })
    const { testRun, testRunLoading, testRunFailed } = useValues(logic)
    const { testPrecheck } = useActions(logic)
    const saved = config.precheck_query ?? null
    // Null until something is typed, so an untouched editor follows the saved query.
    const [draft, setDraft] = useState<string | null>(null)
    // The query the last save or turn-off sent, held until the request settles. The draft clears
    // only if the stored query then matches it, so a query the API rejects stays on screen to fix.
    const [submitted, setSubmitted] = useState<{ query: string | null } | null>(null)
    useEffect(() => {
        if (updating || !submitted) {
            return
        }
        if (saved === submitted.query) {
            setDraft(null)
        }
        setSubmitted(null)
    }, [updating, submitted, saved])
    const text = draft ?? saved ?? ''
    const query = text.trim()
    const changed = query !== (saved ?? '')
    const unsaved = draft !== null && (changed || submitted !== null)
    useEffect(() => {
        onUnsavedChange?.(unsaved)
        return () => onUnsavedChange?.(false)
    }, [unsaved, onUnsavedChange])
    // A result describes the query it ran. Once the query changes, or a newer test is running or
    // failed, it no longer applies.
    const result = testRun && testRun.query === query && !testRunLoading && !testRunFailed ? testRun.result : null
    const disabledReason = updating ? 'Saving scout settings' : undefined
    const saveDisabledReason =
        disabledReason ??
        (query && changed ? undefined : !query && saved ? 'To remove the query, use Turn off' : 'No changes to save')

    return (
        <div className="border-t border-primary pt-2">
            <LemonCollapse
                embedded
                size="small"
                panels={[
                    {
                        key: 'precheck',
                        dataAttr: 'scout-precheck',
                        header: (
                            <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
                                <span className="shrink-0 text-xs text-default">Run only when</span>
                                {saved ? (
                                    <LemonTag size="small" type="option">
                                        Query set
                                    </LemonTag>
                                ) : (
                                    <span className="text-[11.5px] text-muted">Always run</span>
                                )}
                            </div>
                        ),
                        content: (
                            <div className="flex flex-col gap-2">
                                <span className="text-[11.5px] text-muted">
                                    A HogQL query that each scheduled run checks first. When it returns no rows, or a
                                    single false value such as a count of 0, the scout skips the run, so a quiet scout
                                    costs nothing. Otherwise the run starts with the rows the query found. Use{' '}
                                    {'{since}'} for the start of the last run and {'{now}'} for the current time. To run
                                    at least once a week, add {'OR {since} < {now} - INTERVAL 7 DAY'}. A manual run
                                    always starts.
                                </span>
                                <LemonTextArea
                                    value={text}
                                    placeholder={QUERY_PLACEHOLDER}
                                    minRows={4}
                                    maxRows={12}
                                    className="font-mono text-[11.5px]"
                                    disabled={updating}
                                    onChange={setDraft}
                                    aria-label={`${config.skill_name} pre-check query`}
                                />
                                {testRunFailed ? (
                                    <span role="alert" className="text-[11.5px] text-danger">
                                        The test could not run. Try again.
                                    </span>
                                ) : null}
                                {result ? (
                                    <div
                                        className="flex flex-col gap-1 ph-no-capture ph-replay-block"
                                        data-attr="scout-precheck-result"
                                    >
                                        <span
                                            className={`text-[11.5px] ${result.would_run ? 'text-default' : 'text-success'}`}
                                        >
                                            {testVerdict(result)}
                                        </span>
                                        {result.error ? (
                                            <span className="text-[11.5px] text-danger">{result.error}</span>
                                        ) : null}
                                        <span className="text-[11.5px] text-muted">
                                            {'{since}'} is {humanFriendlyDetailedTime(result.since)}.
                                        </span>
                                        {result.rows_text ? (
                                            <pre className="m-0 max-h-40 overflow-auto rounded border border-primary bg-surface-secondary p-2 font-mono text-[11px] whitespace-pre-wrap break-all">
                                                {result.rows_text}
                                            </pre>
                                        ) : null}
                                    </div>
                                ) : null}
                                <div className="flex flex-wrap items-center justify-end gap-2">
                                    {saved ? (
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            status="danger"
                                            className="mr-auto"
                                            disabledReason={disabledReason}
                                            onClick={() =>
                                                LemonDialog.open({
                                                    title: 'Remove the pre-check?',
                                                    description:
                                                        'Every scheduled run starts again. You can add a query again later.',
                                                    primaryButton: {
                                                        children: 'Turn off',
                                                        status: 'danger',
                                                        onClick: () => {
                                                            onUpdate(config.id, { precheck_query: null })
                                                            setSubmitted({ query: null })
                                                        },
                                                        'data-attr': 'scout-precheck-clear',
                                                    },
                                                    secondaryButton: { children: 'Cancel' },
                                                })
                                            }
                                            data-attr="scout-precheck-turn-off"
                                        >
                                            Turn off
                                        </LemonButton>
                                    ) : null}
                                    {unsaved ? (
                                        <LemonButton
                                            size="small"
                                            type="tertiary"
                                            disabledReason={disabledReason}
                                            onClick={() => setDraft(null)}
                                            data-attr="scout-precheck-discard"
                                        >
                                            Discard
                                        </LemonButton>
                                    ) : null}
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        loading={testRunLoading}
                                        // The test reads the stored settings, so it waits for a save to finish.
                                        disabledReason={
                                            testRunLoading
                                                ? 'Testing the query'
                                                : (disabledReason ?? (query ? undefined : 'Write a query first'))
                                        }
                                        onClick={() => testPrecheck({ query })}
                                        data-attr="scout-precheck-test"
                                    >
                                        Test query
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        loading={updating}
                                        disabledReason={saveDisabledReason}
                                        onClick={() => {
                                            onUpdate(config.id, { precheck_query: query })
                                            setSubmitted({ query })
                                        }}
                                        data-attr="scout-precheck-save"
                                    >
                                        Save query
                                    </LemonButton>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
