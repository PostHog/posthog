import { useRef, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { urls } from 'scenes/urls'

import type { WizardRunApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { WizardRunSidebarPanel } from './components/WizardRunSidebarPanel'
import { WizardRunSidebarSummary } from './components/WizardRunSidebarSummary'

export interface WizardRunSidebarWidgetViewProps {
    runs: WizardRunApi[]
    tasksByRunId?: Record<string, readonly WizardRunTaskApi[]>
    onStateClick?: () => void
    onDismissRuns: (runIds: string[]) => void
    initialHovered?: boolean
    initialMenuOpen?: boolean
}

export function WizardRunSidebarWidgetView({
    runs,
    tasksByRunId = {},
    onStateClick,
    onDismissRuns,
    initialHovered = false,
    initialMenuOpen = false,
}: WizardRunSidebarWidgetViewProps): JSX.Element | null {
    const [menuOpen, setMenuOpen] = useState(initialMenuOpen)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const currentRun = runs[0]
    if (!currentRun) {
        return null
    }

    const multiple = runs.length > 1
    const dismissRuns = (runIds: string[]): void => {
        onDismissRuns(runIds)
        if (runs.every((run) => runIds.includes(run.id))) {
            setMenuOpen(false)
        }
    }

    return (
        <Popover
            visible={menuOpen}
            placement="right-end"
            fallbackPlacements={['right-start', 'top-end']}
            padded={false}
            onClickOutside={(event) => {
                setMenuOpen(false)
                if (event instanceof KeyboardEvent) {
                    triggerRef.current?.focus()
                }
            }}
            overlay={
                <WizardRunSidebarPanel
                    runs={runs}
                    tasksByRunId={tasksByRunId}
                    onDismissRuns={dismissRuns}
                    onNavigate={() => setMenuOpen(false)}
                />
            }
        >
            <LemonCard className="group/wizard-run flex w-full min-w-0 items-center p-0" hoverEffect={false}>
                <LemonButton
                    ref={triggerRef}
                    type="tertiary"
                    size="small"
                    fullWidth
                    className="min-w-0 flex-1"
                    sideIcon={null}
                    to={!multiple ? `${urls.wizardRuns()}?run=${encodeURIComponent(currentRun.id)}` : undefined}
                    onClick={() => {
                        onStateClick?.()
                        if (multiple) {
                            setMenuOpen((open) => !open)
                        }
                    }}
                    aria-expanded={multiple ? menuOpen : undefined}
                    aria-haspopup={multiple ? 'dialog' : undefined}
                    data-attr="wizard-run-sidebar-widget"
                >
                    <WizardRunSidebarSummary
                        runs={runs}
                        tasks={tasksByRunId[currentRun.id] ?? []}
                        hovered={initialHovered}
                    />
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    className="mr-1 shrink-0"
                    icon={<IconX />}
                    tooltip={multiple ? 'Dismiss all runs' : 'Dismiss run'}
                    aria-label={multiple ? 'Dismiss all runs' : 'Dismiss run'}
                    onClick={() => dismissRuns(runs.map((run) => run.id))}
                    data-attr="wizard-run-sidebar-dismiss"
                />
            </LemonCard>
        </Popover>
    )
}
