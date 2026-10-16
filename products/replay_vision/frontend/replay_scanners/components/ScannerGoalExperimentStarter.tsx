import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconFlask } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { experimentScannerPickerLogic } from '../experimentScannerPickerLogic'

export interface ScannerGoalExperimentStarterProps {
    disabledReason: string | null
    onDraft: (goal: string, experimentId: number) => void
}

export function ScannerGoalExperimentStarter({
    disabledReason,
    onDraft,
}: ScannerGoalExperimentStarterProps): JSX.Element {
    const { experimentOptions, experimentOptionsLoading, hasLoadedOptions } = useValues(experimentScannerPickerLogic)
    const { ensureOptionsLoaded } = useActions(experimentScannerPickerLogic)
    const [open, setOpen] = useState(false)
    const [experimentId, setExperimentId] = useState<number | null>(null)
    const experiment = experimentOptions.find((option) => option.id === experimentId) ?? null

    return (
        <div className="flex flex-col gap-2">
            <LemonButton
                fullWidth
                icon={<IconFlask />}
                sideIcon={<IconChevronRight className={cn('transition-transform', open && 'rotate-90')} />}
                tooltip="Pick a running experiment and see how people experience each variant"
                disabledReason={disabledReason}
                onClick={() => {
                    setOpen(!open)
                    ensureOptionsLoaded()
                }}
                data-attr="vision-goal-starter-experiment"
            >
                Track an experiment
            </LemonButton>
            {open ? (
                <div className="flex flex-col gap-2 pl-8">
                    <div className="flex flex-col gap-0.5">
                        <span className="text-sm font-semibold">Pick an experiment</span>
                        <span className="text-xs text-muted">
                            The agent drafts a scanner that watches the people in this experiment and describes how each
                            variant plays out for them.
                        </span>
                    </div>
                    <LemonSelect<number>
                        fullWidth
                        placeholder="Select a running experiment"
                        loading={experimentOptionsLoading}
                        disabledReason={
                            hasLoadedOptions && experimentOptions.length === 0 ? 'No running experiments' : undefined
                        }
                        value={experimentId ?? undefined}
                        options={experimentOptions.map((option) => ({ value: option.id, label: option.name }))}
                        onChange={setExperimentId}
                        data-attr="vision-goal-starter-experiment-picker"
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={disabledReason ?? (experiment ? null : 'Select an experiment first')}
                            onClick={() => {
                                if (experiment) {
                                    onDraft(
                                        `Track how people experience the "${experiment.name}" experiment`,
                                        experiment.id
                                    )
                                }
                            }}
                            data-attr="vision-goal-starter-experiment-draft"
                        >
                            Draft my scanner
                        </LemonButton>
                    </div>
                </div>
            ) : null}
        </div>
    )
}
