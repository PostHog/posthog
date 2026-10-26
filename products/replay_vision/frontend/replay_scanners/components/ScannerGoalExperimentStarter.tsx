import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronRight, IconFlask } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'

import { experimentScannerPickerLogic } from '../experimentScannerPickerLogic'

export interface ScannerGoalExperimentStarterProps {
    disabledReason: string | null
    onDraft: (goal: string, experimentId: number) => void
}

export function ScannerGoalExperimentStarter({
    disabledReason,
    onDraft,
}: ScannerGoalExperimentStarterProps): JSX.Element | null {
    const { experimentOptions, experimentOptionsLoading, hasLoadedOptions, loadFailed, search } =
        useValues(experimentScannerPickerLogic)
    const { ensureOptionsLoaded, setSearch } = useActions(experimentScannerPickerLogic)
    const [open, setOpen] = useState(false)
    // Kept as the object because a later search can drop the picked experiment from the options.
    const [experiment, setExperiment] = useState<ExperimentBasicApi | null>(null)
    const options =
        experiment && !experimentOptions.some((option) => option.id === experiment.id)
            ? [experiment, ...experimentOptions]
            : experimentOptions

    useEffect(() => {
        ensureOptionsLoaded()
    }, [ensureOptionsLoaded])

    // Hidden until the first load answers, and when the project runs no experiment to pick. A failed load
    // still shows the starter so that opening the menu can retry.
    if (!loadFailed && (!hasLoadedOptions || (!search && options.length === 0))) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonButton
                fullWidth
                icon={<IconFlask />}
                sideIcon={<IconChevronRight className={cn('transition-transform', open && 'rotate-90')} />}
                tooltip="Pick a running experiment and see how people experience each variant"
                disabledReason={disabledReason}
                onClick={() => setOpen(!open)}
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
                        value={experiment?.id}
                        menu={{ onVisibilityChange: (visible) => visible && ensureOptionsLoaded() }}
                        options={[
                            {
                                title: (
                                    // The menu closes on any click inside it, which would dismiss it when the search box is clicked.
                                    <div onClick={(e) => e.stopPropagation()}>
                                        <LemonInput
                                            type="search"
                                            size="small"
                                            fullWidth
                                            autoFocus
                                            placeholder="Search experiments"
                                            value={search}
                                            onChange={setSearch}
                                            data-attr="vision-goal-starter-experiment-search"
                                        />
                                    </div>
                                ),
                                // LemonSelect drops a section with no options, and the search box with it.
                                options:
                                    options.length > 0
                                        ? options.map((option) => ({ value: option.id, label: option.name }))
                                        : [
                                              {
                                                  value: 0,
                                                  label: experimentOptionsLoading
                                                      ? 'Searching...'
                                                      : loadFailed
                                                        ? "Couldn't load running experiments"
                                                        : 'No running experiments match your search',
                                                  disabledReason: loadFailed
                                                      ? 'Close and reopen this menu to try again'
                                                      : 'Try a different search',
                                              },
                                          ],
                            },
                        ]}
                        onChange={(id) => setExperiment(options.find((option) => option.id === id) ?? null)}
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
