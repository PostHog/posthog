import { useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet/CodeSnippet'

import { Card } from '../dashboard/Card'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'
import type { NextStep } from './nextSteps'

// Mirrors the empty state's "Install with your agent" modal so the two setup surfaces read the same.
function AgentPromptAction({
    step,
    prompt,
    docsUrl,
}: {
    step: NextStep
    prompt: string
    docsUrl: string
}): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconSparkles />}
                onClick={() => setOpen(true)}
                data-attr={`mcp-analytics-activity-next-step-${step.key}`}
            >
                Fix with your agent
            </LemonButton>
            <LemonButton
                type="tertiary"
                size="small"
                to={docsUrl}
                targetBlank
                data-attr={`mcp-analytics-activity-next-step-${step.key}-docs`}
            >
                Docs
            </LemonButton>
            <LemonModal title={step.title} isOpen={open} onClose={() => setOpen(false)} width={640}>
                <p>Open the repository containing your MCP server in your coding agent, then paste this prompt.</p>
                <CodeSnippet wrap compact maxLinesWithoutExpansion={5} thing="prompt">
                    {prompt}
                </CodeSnippet>
                <p className="text-secondary mt-4 mb-0">
                    Once the change is deployed, new tool calls show up here with the extra data.
                </p>
            </LemonModal>
        </>
    )
}

function NextStepActions({ step }: { step: NextStep }): JSX.Element {
    if (step.action.kind === 'link') {
        return (
            <LemonButton
                type="secondary"
                size="small"
                to={step.action.to}
                data-attr={`mcp-analytics-activity-next-step-${step.key}`}
            >
                {step.action.label}
            </LemonButton>
        )
    }
    return <AgentPromptAction step={step} prompt={step.action.prompt} docsUrl={step.action.docsUrl} />
}

export function ActivityNextSteps(): JSX.Element | null {
    const { nextSteps } = useValues(mcpEarlyDataLogic)

    if (nextSteps.length === 0) {
        return null
    }

    return (
        <Card title="Next steps">
            <ul
                className="m-0 flex list-none flex-col divide-y divide-primary p-0"
                data-attr="mcp-analytics-activity-next-steps"
            >
                {nextSteps.map((step) => (
                    <li key={step.key} className="@container py-3 first:pt-0 last:pb-0">
                        <div className="flex flex-col gap-2 @2xl:flex-row @2xl:items-center @2xl:justify-between @2xl:gap-6">
                            <div className="min-w-0">
                                <div className="font-medium">{step.title}</div>
                                <div className="text-muted text-sm">{step.detail}</div>
                            </div>
                            <div className="flex shrink-0 items-center gap-1">
                                <NextStepActions step={step} />
                            </div>
                        </div>
                    </li>
                ))}
            </ul>
        </Card>
    )
}
