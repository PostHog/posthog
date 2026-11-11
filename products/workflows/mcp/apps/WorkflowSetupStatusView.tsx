import { CheckCircle2, Circle } from 'lucide-react'
import { type ReactElement } from 'react'

import { Badge, Button, Card, CardContent } from '@posthog/quill'

export interface WorkflowSetupStep {
    key: string
    done: boolean
    title: string
    next_step: string
    app_url: string
}

export interface WorkflowSetupStatusData {
    steps: WorkflowSetupStep[]
    ready_to_send_email: boolean
    email_sending_paused?: boolean
    next_open_step: string | null
}

export interface WorkflowSetupStatusViewProps {
    data: WorkflowSetupStatusData
    /** The host's link opener. Hosts that sandbox the app without popups block a plain new-tab link. */
    openLink?: (url: string) => void
}

export function WorkflowSetupStatusView({ data, openLink }: WorkflowSetupStatusViewProps): ReactElement {
    const doneCount = data.steps.filter((step) => step.done).length

    return (
        <div className="p-4">
            <Card>
                <CardContent className="flex flex-col gap-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-col">
                            <span className="font-semibold">Messaging setup</span>
                            <span className="text-sm text-muted-foreground">
                                {doneCount} of {data.steps.length} steps done
                            </span>
                        </div>
                        <Badge variant={data.ready_to_send_email ? 'success' : 'warning'}>
                            {data.ready_to_send_email
                                ? 'Ready to send email'
                                : data.email_sending_paused
                                  ? 'Email sending is paused'
                                  : 'Email cannot send yet'}
                        </Badge>
                    </div>
                    <ol className="m-0 flex list-none flex-col gap-3 p-0">
                        {data.steps.map((step) => (
                            <li key={step.key} className="flex items-start gap-3">
                                {step.done ? (
                                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-label="Done" />
                                ) : (
                                    <Circle
                                        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                                        aria-label="Open"
                                    />
                                )}
                                <div className="flex min-w-0 flex-1 flex-col">
                                    <span className={step.done ? 'text-muted-foreground' : 'font-medium'}>
                                        {step.title}
                                    </span>
                                    {!step.done && (
                                        <span className="text-sm text-muted-foreground">{step.next_step}</span>
                                    )}
                                </div>
                                {!step.done && (
                                    <Button
                                        size="sm"
                                        variant={step.key === data.next_open_step ? 'primary' : 'outline'}
                                        render={<a href={step.app_url} target="_blank" rel="noreferrer" />}
                                        onClick={(event) => {
                                            if (openLink) {
                                                event.preventDefault()
                                                openLink(step.app_url)
                                            }
                                        }}
                                    >
                                        Open
                                    </Button>
                                )}
                            </li>
                        ))}
                    </ol>
                </CardContent>
            </Card>
        </div>
    )
}
