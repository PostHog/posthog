import './WizardRailButtonView.scss'

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
    open: boolean
    onOpenChange: (open: boolean) => void
    panel: JSX.Element
}

export function WizardRailButtonView({ state, open, onOpenChange, panel }: WizardRailButtonViewProps): JSX.Element {
    return (
        <Popover open={open} onOpenChange={onOpenChange}>
            <PopoverTrigger
                render={
                    <Button
                        size="icon"
                        aria-label={STATE_LABEL[state]}
                        title={STATE_LABEL[state]}
                        className="size-10 rounded-full data-[popup-open]:bg-[var(--fill-selected)]"
                        data-attr="today-rail-wizard"
                    >
                        <span className="WizardRailButton relative flex size-9 items-center justify-center rounded-full bg-[var(--fill-hover)]">
                            <WizardHog
                                className={cn('size-7', state === 'running' && 'WizardRailButton__hog--working')}
                                loading="eager"
                            />
                            {state === 'running' && (
                                <svg
                                    aria-hidden
                                    viewBox="0 0 40 40"
                                    className="WizardRailButton__ring absolute -inset-0.5 size-10"
                                >
                                    <circle cx="20" cy="20" r="18.5" className="WizardRailButton__ringTrack" />
                                    <circle cx="20" cy="20" r="18.5" className="WizardRailButton__ringArc" />
                                </svg>
                            )}
                            {(state === 'completed' || state === 'failed') && (
                                <span
                                    aria-hidden
                                    className={cn(
                                        'absolute -end-0.5 -bottom-0.5 flex size-3.5 items-center justify-center rounded-full ring-2 ring-[var(--chrome)] [&_svg]:size-2.5',
                                        state === 'completed'
                                            ? 'bg-[var(--success-foreground)]'
                                            : 'bg-[var(--destructive-foreground)]'
                                    )}
                                >
                                    {state === 'completed' ? (
                                        <IconCheck className="text-white" />
                                    ) : (
                                        <IconX className="text-white" />
                                    )}
                                </span>
                            )}
                        </span>
                    </Button>
                }
            />
            <PopoverContent side="right" align="end" className="w-auto overflow-hidden p-0">
                {panel}
            </PopoverContent>
        </Popover>
    )
}
