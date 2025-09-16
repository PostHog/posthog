import { useEffect, useMemo, useState } from 'react'

import { IconInfo, IconMagicWand, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag, Popover, Tooltip } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

export function FixWithAIButton(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [status, setStatus] = useState<FixWithAIStatus>('idle')
    const [hasStarted, setHasStarted] = useState(false)
    const prLink = useMemo(() => 'https://github.com/posthog/posthog/pull/42424', [])

    useEffect(() => {
        if (status === 'in_progress') {
            const timeout = setTimeout(() => setStatus('done'), 3000)
            return () => clearTimeout(timeout)
        }
    }, [status])

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <FixWithAIPopoverContent
                    status={status}
                    setStatus={setStatus}
                    hasStarted={hasStarted}
                    setHasStarted={setHasStarted}
                    prLink={prLink}
                />
            }
            placement="bottom-end"
            padded={false}
            showArrow
        >
            <span>
                <ButtonPrimitive
                    onClick={() => setIsOpen((v) => !v)}
                    className="px-2 h-[1.4rem]"
                    tooltip="Generate AI prompt to fix this error"
                >
                    <IconMagicWand />
                    Fix with AI
                    <LemonTag size="small" type="danger">
                        Experimental
                    </LemonTag>
                </ButtonPrimitive>
            </span>
        </Popover>
    )
}

export function FixWithAIPopoverContent({
    status,
    setStatus,
    hasStarted,
    setHasStarted,
    prLink,
}: {
    status: FixWithAIStatus
    setStatus: (s: FixWithAIStatus) => void
    hasStarted: boolean
    setHasStarted: (v: boolean) => void
    prLink: string
}): JSX.Element {
    const isInProgress = status === 'in_progress'
    const isDone = status === 'done'

    return (
        <div className="overflow-hidden min-w-[300px]">
            <div className="border-b-1 p-2 flex items-center justify-between gap-3">
                <h4 className="mb-0">Fix with AI</h4>
                <Tooltip
                    title="Our agent will attempt to reproduce and fix this issue, open a PR with the changes, and share a link
                    here."
                >
                    <IconInfo className="text-muted-alt" />
                </Tooltip>
            </div>
            <div className="p-2">
                <div className="mt-2 flex items-center gap-2">
                    <LemonTag type={isDone ? 'success' : isInProgress ? 'highlight' : 'muted'} className="uppercase">
                        {isDone ? 'Done' : isInProgress ? 'In progress' : 'Idle'}
                    </LemonTag>
                    {isInProgress && <span className="text-xxs text-tertiary">This can take a few minutes…</span>}
                </div>

                <div className="mt-3 flex items-center gap-2">
                    {!isDone ? (
                        <LemonButton
                            type="primary"
                            icon={<IconSparkles />}
                            onClick={() => {
                                setHasStarted(true)
                                setStatus('in_progress')
                            }}
                            disabled={isInProgress}
                        >
                            {isInProgress ? 'Starting…' : hasStarted ? 'Restart' : 'Start fix'}
                        </LemonButton>
                    ) : (
                        <LemonButton type="primary" to={prLink} targetBlank>
                            Open PR
                        </LemonButton>
                    )}

                    {hasStarted && !isDone && (
                        <LemonButton type="secondary" onClick={() => setStatus('idle')} disabled={isInProgress}>
                            Reset
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}
