import { useActions, useValues } from 'kea'

import { IconExternal, IconRefresh, IconUpload } from '@posthog/icons'
import { LemonButton, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import {
    RUN_NOTE_MAX_CHARS,
    runNoteSubmitDisabledReason,
    scoutDetailActionsLogic,
} from '../../../logics/scoutDetailActionsLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { SCOUT_PUBLISH_TOOLTIP, SCOUT_RUN_NOW_TOOLTIP, SCOUT_VIEW_SKILL_TOOLTIP } from './scoutDetailActionCopy'
import { LeaveScoutNoteButton } from './ScoutNotesPanel'
import { ScoutRubricsButton } from './ScoutRubricsButton'
import { ScoutSettingsButton } from './ScoutSettingsModal'

/** The draft lives in the logic, so a failed run keeps the note for a retry. */
function ScoutRunNoteForm({ configId }: { configId: string }): JSX.Element {
    const { manualRunScoutIds, runNoteDrafts } = useValues(scoutFleetLogic)
    const { runScoutNow, setRunNoteDraft } = useActions(scoutFleetLogic)
    const running = manualRunScoutIds.includes(configId)
    const note = runNoteDrafts[configId] ?? ''

    return (
        <div className="flex w-80 max-w-full flex-col gap-2 p-1">
            <div className="text-sm font-semibold">Run with a note</div>
            <p className="mb-0 text-xs text-secondary">
                The note steers this run only. To steer every later run, use Tell it something.
            </p>
            <LemonTextArea
                autoFocus
                value={note}
                maxLength={RUN_NOTE_MAX_CHARS}
                placeholder="e.g. focus on the checkout regression"
                onChange={(value) => setRunNoteDraft(configId, value)}
            />
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={running}
                    disabledReason={runNoteSubmitDisabledReason(running, note)}
                    onClick={() => runScoutNow(configId, note)}
                >
                    Run
                </LemonButton>
            </div>
        </div>
    )
}

export function ScoutDetailActions({ config }: { config: SignalScoutConfig }): JSX.Element {
    const logic = scoutDetailActionsLogic({ skillName: config.skill_name })
    const { running, updating, publishing, publishDisabledReason, canPublish, runNoteDisabledReason, runNoteOpen } =
        useValues(logic)
    const { setRunNoteOpen, runNow, publish, skillOpened } = useActions(logic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)

    return (
        <>
            <LeaveScoutNoteButton skillName={config.skill_name} />
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconRefresh />}
                loading={running}
                disabledReason={running ? 'Starting a run' : undefined}
                tooltip={SCOUT_RUN_NOW_TOOLTIP}
                onClick={runNow}
                sideAction={{
                    tooltip: 'Run with a note',
                    'aria-label': 'Run with a note',
                    'data-attr': 'scout-run-now-with-note',
                    disabledReason: runNoteDisabledReason,
                    dropdown: {
                        placement: 'bottom-end',
                        closeOnClickInside: false,
                        visible: runNoteOpen,
                        onVisibilityChange: setRunNoteOpen,
                        overlay: <ScoutRunNoteForm configId={config.id} />,
                    },
                }}
            >
                Run now
            </LemonButton>
            <ScoutSettingsButton config={config} showLabel />
            <ScoutRubricsButton config={config} />
            {canPublish && (
                <Tooltip title={SCOUT_PUBLISH_TOOLTIP}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconUpload />}
                        loading={publishing}
                        disabledReason={publishDisabledReason}
                        onClick={publish}
                    >
                        Publish
                    </LemonButton>
                </Tooltip>
            )}
            {/* Captured on the way down: Link swallows Cmd/Ctrl-clicks before its onClick runs, and
            those opens count too. */}
            <span className="contents" onClickCapture={skillOpened}>
                <Tooltip title={SCOUT_VIEW_SKILL_TOOLTIP}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconExternal />}
                        to={urls.skill(config.skill_name)}
                    >
                        View skill
                    </LemonButton>
                </Tooltip>
            </span>
            <ScoutEnabledSwitch config={config} onUpdate={updateScoutConfig} updating={updating} />
        </>
    )
}
