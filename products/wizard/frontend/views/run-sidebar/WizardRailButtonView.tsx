import './WizardRailButtonView.scss'

import { IconCheck, IconX } from '@posthog/icons'
import { Popover, PopoverContent, PopoverTrigger, cn } from '@posthog/quill'

import { WizardHog } from 'scenes/onboarding/shared/wizardHog'

import { TodayRailTile } from '~/layout/today/TodayRailTile'

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
                    <TodayRailTile
                        label="Wizard"
                        aria-label={STATE_LABEL[state]}
                        active={open}
                        dataAttr="today-rail-wizard"
                        icon={
                            <>
                                <WizardHog
                                    className={cn('size-7', state === 'running' && 'WizardRailButton__hog--working')}
                                    loading="eager"
                                />
                                {state === 'running' && <span aria-hidden className="WizardRailButton__ring" />}
                                {(state === 'completed' || state === 'failed') && (
                                    <span
                                        aria-hidden
                                        className={cn(
                                            'WizardRailButton__badge absolute -end-1 -bottom-1 flex size-4 items-center justify-center rounded-full ring-2 ring-[var(--chrome)]',
                                            state === 'completed'
                                                ? 'bg-[var(--success-foreground)]'
                                                : 'bg-[var(--destructive-foreground)]'
                                        )}
                                    >
                                        {state === 'completed' ? <IconCheck /> : <IconX />}
                                    </span>
                                )}
                            </>
                        }
                    />
                }
            />
            <PopoverContent side="right" align="start" className="w-auto overflow-hidden p-0">
                {panel}
            </PopoverContent>
        </Popover>
    )
}
