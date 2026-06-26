import { LemonButton } from '@posthog/lemon-ui'

import { BuilderHog3, WavingHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import type { MCPOnboardingState } from './mcpAnalyticsOnboardingLogic'

const DOCS_URL = 'https://posthog.com/docs/mcp-analytics'

/** Shown until the project captures its first `$mcp_tool_call`. Routes setup into the onboarding flow. */
export function MCPAnalyticsOnboarding({ state }: { state: Exclude<MCPOnboardingState, 'onboarded'> }): JSX.Element {
    const connected = state === 'connected-no-calls'

    return (
        <ProductIntroduction
            productName="MCP analytics"
            thingName="tool call"
            isEmpty
            customHog={connected ? WavingHog : BuilderHog3}
            titleOverride={connected ? "You're connected — now make a tool call" : 'See how agents use your MCP server'}
            description={
                connected
                    ? "We've seen your MCP server connect, but it hasn't handled a tool call yet. Trigger a tool from your agent and this page fills in on its own."
                    : 'Instrument your MCP server with the @posthog/mcp SDK and every tool call, agent intent, and failure lands here.'
            }
            docsURL={DOCS_URL}
            actionElementOverride={
                connected ? (
                    <p className="text-sm text-secondary m-0">
                        Waiting for the first <code>$mcp_tool_call</code> — this page refreshes itself.
                    </p>
                ) : (
                    <LemonButton
                        type="primary"
                        to={urls.onboarding({
                            productKey: ProductKey.MCP_ANALYTICS,
                            stepKey: OnboardingStepKey.INSTALL,
                        })}
                    >
                        Set up MCP analytics
                    </LemonButton>
                )
            }
        />
    )
}
