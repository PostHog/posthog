import { IconCheck } from '@posthog/icons'
import { Text, cn } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { ReleaseLifecycleStep } from './releaseUtils'

export function ReleaseLifecycle({ steps }: { steps: ReleaseLifecycleStep[] }): JSX.Element {
    return (
        <ol className="m-0 flex list-none p-0" aria-label="Release progress">
            {steps.map((step, index) => (
                <li
                    key={step.key}
                    className="flex min-w-0 flex-1 flex-col gap-1.5"
                    aria-current={step.state === 'current' ? 'step' : undefined}
                >
                    <div className="flex items-center">
                        <span
                            className={cn(
                                'flex size-5 shrink-0 items-center justify-center rounded-full border',
                                step.state === 'done' && 'border-border text-success-foreground',
                                step.state === 'current' && 'border-primary bg-primary text-primary-foreground',
                                step.state === 'upcoming' && 'border-dashed border-border'
                            )}
                        >
                            {step.state === 'done' ? (
                                <IconCheck className="size-3" />
                            ) : step.state === 'current' ? (
                                <span className="size-1.5 rounded-full bg-background" />
                            ) : null}
                        </span>
                        {index < steps.length - 1 && (
                            <span
                                className={cn(
                                    'mx-2 h-px flex-1',
                                    step.state === 'done' ? 'bg-foreground' : 'bg-border'
                                )}
                            />
                        )}
                    </div>
                    <div className="flex min-w-0 flex-col pr-2">
                        <Text
                            size="xs"
                            weight={step.state === 'current' ? 'semibold' : 'medium'}
                            variant={step.state === 'upcoming' ? 'muted' : 'default'}
                            className="truncate"
                        >
                            {step.label}
                        </Text>
                        <Text size="xxs" variant="muted" render={<span />} className="truncate">
                            {step.date ? (
                                <TZLabel time={step.date} formatDate="D MMM" formatTime="" noStyles />
                            ) : step.state === 'upcoming' ? (
                                'Not yet'
                            ) : (
                                ' '
                            )}
                        </Text>
                    </div>
                </li>
            ))}
        </ol>
    )
}
