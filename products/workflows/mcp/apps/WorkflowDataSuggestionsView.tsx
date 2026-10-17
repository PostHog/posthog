import { type ReactElement } from 'react'

import { Button, Card, CardContent } from '@posthog/quill'

import { WorkflowDataSuggestionBuildView } from './WorkflowDataSuggestionBuildView'

export interface WorkflowDataSuggestion {
    id: string
    name: string
    description: string
    reason: string
    trigger_event: string
    weekly_count: number
}

export interface WorkflowDataSuggestionsData {
    status: 'ready' | 'generating' | 'ai_not_approved' | 'unavailable'
    suggestions: WorkflowDataSuggestion[]
    email_sender_ready?: boolean
}

export interface WorkflowDataSuggestionMissingInput {
    step_name: string
    field: string
}

export type WorkflowDataSuggestionBuild =
    | { status: 'building' }
    | { status: 'ready'; editorUrl: string | null; missingInputs: WorkflowDataSuggestionMissingInput[] }
    | { status: 'failed'; error: string }

export interface WorkflowDataSuggestionsViewProps {
    data: WorkflowDataSuggestionsData
    builds: Record<string, WorkflowDataSuggestionBuild>
    onCreate?: (suggestion: WorkflowDataSuggestion, retry: boolean) => void
}

const EMPTY_MESSAGES: Record<Exclude<WorkflowDataSuggestionsData['status'], 'ready'>, string> = {
    generating: 'Suggesting workflows from the events your project sends. This takes a few seconds.',
    ai_not_approved: 'Suggestions need AI data processing, which this organization has not approved.',
    unavailable: 'There are no suggestions for this project right now.',
}

export function WorkflowDataSuggestionsView({
    data,
    builds,
    onCreate,
}: WorkflowDataSuggestionsViewProps): ReactElement {
    if (data.status !== 'ready' || data.suggestions.length === 0) {
        return (
            <p className="p-4 text-sm text-muted-foreground">
                {data.status === 'ready' ? EMPTY_MESSAGES.unavailable : EMPTY_MESSAGES[data.status]}
            </p>
        )
    }
    const building = Object.values(builds).some((build) => build.status === 'building')

    return (
        <div className="flex flex-col gap-3 p-4">
            {data.email_sender_ready === false ? (
                <p className="m-0 text-sm text-muted-foreground">
                    This project can't send email yet. You can create these as drafts now, then add and verify a sending
                    domain under Workflows &gt; Channels before you turn them on.
                </p>
            ) : null}
            {data.suggestions.map((suggestion, index) => (
                <SuggestionCard
                    key={suggestion.id}
                    suggestion={suggestion}
                    // The top-ranked suggestion is the one primary action, like on the Workflows empty state.
                    primary={index === 0}
                    build={builds[suggestion.id]}
                    disabled={building && builds[suggestion.id]?.status !== 'building'}
                    onCreate={onCreate}
                />
            ))}
        </div>
    )
}

function SuggestionCard({
    suggestion,
    primary,
    build,
    disabled,
    onCreate,
}: {
    suggestion: WorkflowDataSuggestion
    primary: boolean
    build: WorkflowDataSuggestionBuild | undefined
    disabled: boolean
    onCreate: WorkflowDataSuggestionsViewProps['onCreate']
}): ReactElement {
    return (
        <Card>
            <CardContent className="flex flex-col gap-2 p-4">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="font-semibold">{suggestion.name}</span>
                    <span className="text-xs text-muted-foreground">
                        <code>{suggestion.trigger_event}</code> · {suggestion.weekly_count.toLocaleString()} this week
                    </span>
                </div>
                <p className="m-0 text-sm">{suggestion.description}</p>
                <p className="m-0 text-sm text-muted-foreground">{suggestion.reason}</p>
                {build?.status === 'ready' ? (
                    <WorkflowDataSuggestionBuildView build={build} />
                ) : (
                    <div className="flex flex-wrap items-center gap-3">
                        {onCreate ? (
                            <Button
                                variant={primary ? 'primary' : 'outline'}
                                size="sm"
                                disabled={disabled || build?.status === 'building'}
                                onClick={() => onCreate(suggestion, build?.status === 'failed')}
                            >
                                {build?.status === 'building' ? 'Building your workflow…' : 'Create workflow'}
                            </Button>
                        ) : null}
                        {build?.status === 'failed' ? (
                            <span className="text-sm text-destructive">{build.error}</span>
                        ) : null}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
