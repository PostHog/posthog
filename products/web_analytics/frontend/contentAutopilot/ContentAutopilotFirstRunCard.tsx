import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotSetupCostNote } from './ContentAutopilotSetupCostNote'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

const CHECKLIST = [
    { tab: 'prompts', label: 'Review your prompts', detail: 'Edit or pause the questions PostHog saved.' },
    { tab: 'keywords', label: 'Review your keywords', detail: "Remove any you don't need." },
    { tab: 'settings', label: 'Choose engines', detail: 'Turn engines on or off and set how often they run.' },
] as const

/** The overview of a project that has prompts but no checks yet. */
export const ContentAutopilotFirstRunCard = ({ prompts }: { prompts: number }): JSX.Element => {
    const { setupContext, selectedEngines, startDisabledReason, starting, startError, firstRunQueued } =
        useValues(contentAutopilotSetupLogic)
    const { startSetup } = useActions(contentAutopilotSetupLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const runDisabledReason =
        startDisabledReason ??
        (setupContext && !setupContext.first_run_available ? "Checks aren't available for this project yet" : undefined)

    return (
        <LemonCard hoverEffect={false} className="p-6" data-attr="content-autopilot-first-run">
            {firstRunQueued ? (
                <>
                    <h3 className="m-0">The first checks are running</h3>
                    <p className="m-0 mt-1 text-muted">
                        Each engine is answering your prompts. Results show up here as the checks finish, which takes a
                        few minutes.
                    </p>
                </>
            ) : (
                <>
                    <h3 className="m-0">Your prompts are ready</h3>
                    <p className="m-0 mt-1 text-muted">
                        The daily schedule runs the first checks. To see results sooner, run them now.
                    </p>
                    <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
                        <div className="min-w-0 flex-1 basis-80">
                            <ContentAutopilotSetupCostNote prompts={prompts} engines={selectedEngines.length} />
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={() => startSetup(true)}
                            loading={starting}
                            disabledReason={runDisabledReason}
                            data-attr="content-autopilot-first-run-now"
                        >
                            Run checks now
                        </LemonButton>
                    </div>
                    {startError ? (
                        <LemonBanner type="error" className="mt-4">
                            {startError}
                        </LemonBanner>
                    ) : null}
                </>
            )}
            <ul className="m-0 mt-5 flex list-none flex-col gap-2 border-t p-0 pt-4">
                {CHECKLIST.map((item) => (
                    <li key={item.tab}>
                        <LemonButton
                            fullWidth
                            sideIcon={<IconArrowRight />}
                            onClick={() => setWorkspaceTab(item.tab)}
                            data-attr={`content-autopilot-first-run-${item.tab}`}
                        >
                            <span className="flex flex-col items-start">
                                <span>{item.label}</span>
                                <span className="text-xs font-normal text-secondary">{item.detail}</span>
                            </span>
                        </LemonButton>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}
