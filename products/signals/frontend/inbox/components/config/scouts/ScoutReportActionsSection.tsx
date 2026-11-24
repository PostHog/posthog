import { useState } from 'react'

import { LemonButton, LemonCollapse, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import {
    MAX_SCOUT_REPORT_ACTIONS_PER_DAY,
    SCOUT_REPORT_ACTION_ROWS,
    scoutReportActionLabels,
} from './scoutReportActions'

interface ReportActionsDraft {
    actions: string[]
    /** Undefined while the number field is empty. */
    limit: number | undefined
}

/**
 * Report actions for one scout in its settings form: collapsed by default, with the actions it
 * holds in the header.
 *
 * Saves on the button, not on change, like write access. Each action starts an agent run that acts
 * as a person, so a stray click must not widen what an unattended scout can start.
 *
 * The switches stay live for everyone. Only the person the scout's runs act as can widen the grant,
 * a project admin can only narrow it, and the client cannot resolve the former, so the API refuses
 * and its message names who can.
 */
export function ScoutReportActionsSection({
    config,
    onUpdate,
    updating = false,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}): JSX.Element {
    const savedActions = [...(config.report_actions ?? [])]
    const savedLimit = config.max_report_actions_per_day
    // Null until something is edited, so the saved grant stays the truth, including after a rejected
    // save, which must leave the section where the server has it rather than where it was left.
    const [draft, setDraft] = useState<ReportActionsDraft | null>(null)
    const current: ReportActionsDraft = draft ?? { actions: savedActions, limit: savedLimit }
    const actionsChanged = [...current.actions].sort().join() !== [...savedActions].sort().join()
    const limitChanged = current.limit !== savedLimit
    const limitValid =
        current.limit !== undefined &&
        Number.isInteger(current.limit) &&
        current.limit >= 0 &&
        current.limit <= MAX_SCOUT_REPORT_ACTIONS_PER_DAY
    const heldLabels = scoutReportActionLabels(savedActions)
    const disabledReason = updating ? 'Saving scout settings' : undefined

    const toggleAction = (action: string, granted: boolean): void => {
        // Other held actions ride along untouched, including one this form has no switch for yet.
        const others = current.actions.filter((held) => held !== action)
        setDraft({ ...current, actions: granted ? [...others, action] : others })
    }

    const save = (): void => {
        const updates: SignalScoutConfigUpdate = {}
        if (actionsChanged) {
            updates.report_actions = current.actions
        }
        if (limitChanged) {
            updates.max_report_actions_per_day = current.limit
        }
        onUpdate(config.id, updates)
        setDraft(null)
    }

    return (
        <div className="border-t border-primary pt-2">
            <LemonCollapse
                embedded
                size="small"
                panels={[
                    {
                        key: 'report-actions',
                        dataAttr: 'scout-report-actions',
                        header: (
                            <div className="flex flex-1 items-center justify-between gap-2">
                                <span className="text-xs text-default">Report actions</span>
                                <div className="flex flex-wrap items-center gap-1">
                                    {heldLabels.length > 0 ? (
                                        heldLabels.map((label) => (
                                            <LemonTag key={label} size="small" type={config.emit ? 'option' : 'muted'}>
                                                {label}
                                            </LemonTag>
                                        ))
                                    ) : (
                                        <span className="text-[11.5px] text-muted">None</span>
                                    )}
                                    {heldLabels.length > 0 && !config.emit && (
                                        <span className="text-[11.5px] text-muted">Inactive during dry run</span>
                                    )}
                                </div>
                            </div>
                        ),
                        content: (
                            <div className="flex flex-col gap-2">
                                <p className="text-[11.5px] text-muted mb-0">
                                    Each action starts an agent run with the full access of the person this scout's runs
                                    act as. A scout cannot send its own message with an action. The daily limit counts a
                                    rolling 24 hours across all of this scout's runs. Changes apply from the scout's
                                    next run.
                                </p>
                                {SCOUT_REPORT_ACTION_ROWS.map((row) => (
                                    <div key={row.action} className="flex items-center justify-between gap-3">
                                        <div className="flex min-w-0 flex-col">
                                            <span className="text-xs text-default">{row.label}</span>
                                            <span className="text-[11.5px] text-muted">{row.description}</span>
                                        </div>
                                        <LemonSwitch
                                            size="small"
                                            checked={current.actions.includes(row.action)}
                                            disabledReason={disabledReason}
                                            onChange={(checked) => toggleAction(row.action, checked)}
                                            aria-label={`Let this scout start ${row.label.toLowerCase()}`}
                                        />
                                    </div>
                                ))}
                                <div className="flex items-center justify-between gap-3">
                                    <div className="flex min-w-0 flex-col">
                                        <span className="text-xs text-default">Daily limit</span>
                                        <span className="text-[11.5px] text-muted">
                                            Most actions this scout can start in 24 hours, from 0 to{' '}
                                            {MAX_SCOUT_REPORT_ACTIONS_PER_DAY}
                                        </span>
                                    </div>
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        max={MAX_SCOUT_REPORT_ACTIONS_PER_DAY}
                                        step={1}
                                        size="small"
                                        className="w-20 shrink-0"
                                        value={current.limit}
                                        disabledReason={disabledReason}
                                        onChange={(value) => setDraft({ ...current, limit: value })}
                                        aria-label="Daily report action limit"
                                    />
                                </div>
                                <div className="flex justify-end">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        loading={updating}
                                        disabledReason={
                                            disabledReason ??
                                            (!limitValid
                                                ? `Enter a daily limit from 0 to ${MAX_SCOUT_REPORT_ACTIONS_PER_DAY}`
                                                : actionsChanged || limitChanged
                                                  ? undefined
                                                  : 'No changes to save')
                                        }
                                        onClick={save}
                                        data-attr="scout-report-actions-save"
                                    >
                                        Save report actions
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
