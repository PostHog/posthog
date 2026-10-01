import { ReactNode } from 'react'

import { Card, Heading, Text } from '@posthog/quill'

import { TaskUserAvatar, taskUserName } from '../TaskUserAvatar'
import { SpaceLoop } from './spaceLoops'

function SummaryRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Text render={<span />} size="xs" variant="muted" className="uppercase tracking-wide">
                {label}
            </Text>
            <div className="text-sm">{children}</div>
        </div>
    )
}

export function SpaceLoopConfiguration({ loop }: { loop: SpaceLoop }): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <Heading size="sm" render={<h2 />}>
                Configuration
            </Heading>
            <Card className="flex flex-col gap-4 p-4">
                <SummaryRow label="Model">
                    {[loop.model || 'Default model', loop.reasoningEffort ? `${loop.reasoningEffort} reasoning` : null]
                        .filter(Boolean)
                        .join(' · ')}
                </SummaryRow>
                <SummaryRow label="Repository">
                    {loop.repositories.length ? loop.repositories.join(', ') : 'None (connector-only loop)'}
                </SummaryRow>
                {loop.createdBy && (
                    <SummaryRow label="Created by">
                        <span className="flex items-center gap-2">
                            <TaskUserAvatar user={loop.createdBy} className="size-5" />
                            <span>{taskUserName(loop.createdBy)}</span>
                        </span>
                    </SummaryRow>
                )}
                <SummaryRow label="Triggers">
                    {loop.triggers.length ? (
                        <span className="flex flex-col gap-1">
                            {loop.triggers.map((trigger) => (
                                <span key={trigger}>{trigger}</span>
                            ))}
                        </span>
                    ) : (
                        'No triggers configured'
                    )}
                </SummaryRow>
                {loop.notifications.length > 0 && (
                    <SummaryRow label="Notifications">{loop.notifications.join(', ')}</SummaryRow>
                )}
            </Card>
        </section>
    )
}
