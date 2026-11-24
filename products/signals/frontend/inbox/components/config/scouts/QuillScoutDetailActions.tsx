import { useActions, useValues } from 'kea'

import { IconChevronDown, IconExternal, IconGear, IconPencil, IconRefresh } from '@posthog/icons'
import { Button, ButtonGroup, Popover, PopoverContent, PopoverTrigger, Switch } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutDetailActionsLogic } from '../../../logics/scoutDetailActionsLogic'
import { scoutDisplayName } from '../../../utils/scoutRunsWindow'
import { QuillScoutRunNoteForm } from './QuillScoutRunNoteForm'
import { SCOUT_RUN_NOW_TOOLTIP, SCOUT_VIEW_SKILL_TOOLTIP } from './scoutDetailActionCopy'

export function QuillScoutDetailActions({ config }: { config: SignalScoutConfig }): JSX.Element {
    const logic = scoutDetailActionsLogic({ skillName: config.skill_name })
    const { running, updating, savingNote, noteDisabledReason, runNoteDisabledReason, runNoteOpen } = useValues(logic)
    const { runNow, leaveNote, setEnabled, setRunNoteOpen, openDialog, skillOpened } = useActions(logic)

    return (
        <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="outline" loading={savingNote} disabledReason={noteDisabledReason} onClick={leaveNote}>
                <IconPencil />
                Tell it something
            </Button>
            <ButtonGroup>
                <Button
                    variant="outline"
                    loading={running}
                    disabledReason={running ? 'Starting a run' : undefined}
                    tooltip={SCOUT_RUN_NOW_TOOLTIP}
                    onClick={runNow}
                >
                    <IconRefresh />
                    Run now
                </Button>
                <Popover open={runNoteOpen} onOpenChange={setRunNoteOpen}>
                    <PopoverTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon"
                                aria-label="Run with a note"
                                tooltip="Run with a note"
                                disabledReason={runNoteDisabledReason}
                                data-attr="scout-run-now-with-note"
                            />
                        }
                    >
                        <IconChevronDown />
                    </PopoverTrigger>
                    <PopoverContent align="end">
                        <QuillScoutRunNoteForm configId={config.id} />
                    </PopoverContent>
                </Popover>
            </ButtonGroup>
            <Button variant="outline" onClick={() => openDialog('settings')}>
                <IconGear />
                Settings
            </Button>
            {/* Captured on the way down: the link swallows Cmd/Ctrl-clicks before its onClick runs, and those opens
                count too. */}
            <Button
                variant="outline"
                tooltip={SCOUT_VIEW_SKILL_TOOLTIP}
                nativeButton={false}
                render={<LinkPrimitive to={urls.skill(config.skill_name)} />}
                onClickCapture={skillOpened}
            >
                <IconExternal />
                View skill
            </Button>
            <Switch
                checked={config.enabled}
                onCheckedChange={(checked: boolean) => setEnabled(checked)}
                disabledReason={updating ? 'Saving scout settings' : undefined}
                aria-label={`${scoutDisplayName(config)} enabled`}
            />
        </div>
    )
}
