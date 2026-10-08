import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

// Kept in sync with the MCP note in services/mcp/src/tools/workflows/workflowSizeHooks.ts.
const SPLIT_SUGGESTION_STEP_COUNT = 50

export function WorkflowSplitSuggestion(props: WorkflowLogicProps): JSX.Element | null {
    const { workflow } = useValues(workflowLogic(props))
    const stepCount = workflow.actions.length
    const show = !!workflow.id && workflow.id !== 'new' && stepCount > SPLIT_SUGGESTION_STEP_COUNT

    useEffect(() => {
        if (show) {
            // pinned: analytics event names, renaming breaks dashboards
            posthog.capture('workflow split suggestion shown', { step_count: stepCount })
        }
        // Capture once per workflow, not on every edit that changes the step count.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [show, workflow.id])

    if (!show) {
        return null
    }

    const prompt = `Split my PostHog workflow "${workflow.name}" (id ${workflow.id}) into smaller workflows. First propose where to split it and wait for my approval. Then build each part as a draft workflow, chained with Capture event steps. Do not change or disable the original workflow.`

    return (
        <LemonBanner
            type="info"
            className="m-2"
            dismissKey={`workflow-split-suggestion-${workflow.id}`}
            action={{
                children: 'Copy prompt',
                onClick: () => {
                    void copyToClipboard(prompt, 'prompt')
                    posthog.capture('workflow split prompt copied', { step_count: stepCount })
                },
                'data-attr': 'workflow-split-copy-prompt',
            }}
        >
            <div className="flex flex-col gap-1">
                <span className="font-semibold">{stepCount} steps is a lot of workflow</span>
                <span>
                    Smaller workflows open faster and are easier to change. Paste the prompt into an AI assistant with
                    the PostHog MCP and it splits this one into drafts for you.{' '}
                    <Link
                        to={urls.settings('posthog-mcp')}
                        onClick={() => posthog.capture('workflow split mcp setup clicked', { step_count: stepCount })}
                        data-attr="workflow-split-mcp-setup"
                    >
                        Set up the MCP
                    </Link>
                </span>
            </div>
        </LemonBanner>
    )
}
