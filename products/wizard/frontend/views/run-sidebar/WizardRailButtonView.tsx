import './WizardRailButtonView.scss'

import type { CSSProperties } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, cn } from '@posthog/quill'

import { WizardHog } from 'scenes/onboarding/shared/wizardHog'

import type { WizardRailState } from './wizardRunSidebarLogic'

const STATE_LABEL: Record<WizardRailState, string> = {
    idle: 'Wizard',
    running: 'Wizard, setup agent running',
    completed: 'Wizard, run finished',
    failed: 'Wizard, run failed',
}

export interface WizardRailButtonViewProps {
    state: WizardRailState
    progress: number
    open: boolean
    onOpenChange: (open: boolean) => void
    panel: JSX.Element
}

export function WizardRailButtonView({
    state,
    progress,
    open,
    onOpenChange,
    panel,
}: WizardRailButtonViewProps): JSX.Element {
    const percent = Math.round(progress * 100)
    return (
        <Popover open={open} onOpenChange={onOpenChange}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label={
                            state === 'running' ? `${STATE_LABEL[state]}, ${percent}% done` : STATE_LABEL[state]
                        }
                        aria-pressed={open}
                        tooltip={open ? null : 'Wizard'}
                        className="relative shrink-0 aria-pressed:bg-[var(--fill-selected)]"
                        // pinned: autocapture data-attr kept from when the button sat on the rail
                        data-attr="today-rail-wizard"
                    >
                        <WizardHog
                            className={cn('size-5', state === 'running' && 'WizardRailButton__hog--working')}
                            loading="eager"
                        />
                        {state === 'running' && (
                            <span
                                aria-hidden
                                className="WizardRailButton__ring"
                                // A run that just started still shows a sliver, so the ring reads as progress.
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ '--wizard-rail-progress': Math.max(progress, 0.03) } as CSSProperties}
                            />
                        )}
                        {(state === 'completed' || state === 'failed') && (
                            <span
                                aria-hidden
                                className={cn(
                                    'WizardRailButton__badge absolute -end-1 -bottom-1 flex size-2.5 items-center justify-center rounded-full',
                                    `WizardRailButton__badge--${state}`
                                )}
                            >
                                {state === 'completed' ? <IconCheck /> : <IconX />}
                            </span>
                        )}
                    </Button>
                }
            />
            <PopoverContent side="bottom" align="start" className="w-auto overflow-hidden p-0">
                {panel}
            </PopoverContent>
        </Popover>
    )
}
