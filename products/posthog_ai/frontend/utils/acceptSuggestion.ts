import { getInsightId } from 'scenes/insights/utils'
import { urls } from 'scenes/urls'

import type { CyclotronJobInputSchemaType, InsightShortId } from '~/types'

import { alertsCreate, alertsDestinationsCreate } from 'products/alerts/frontend/generated/api'
import { hogFunctionTemplatesRetrieve, hogFunctionsCreate } from 'products/cdp/frontend/generated/api'
import { notebooksCreate } from 'products/notebooks/frontend/generated/api'
import { signalsScoutCreate } from 'products/signals/frontend/generated/api'
import { subscriptionsCreate } from 'products/subscriptions/frontend/generated/api'

import type { AlertSuggestionDirection, ScoutSuggestionCadence, TurnSuggestion } from '../types/streamTypes'
import { ConversationBlocks, buildConversationNotebook } from './conversationNotebook'
import {
    ERROR_ALERT_SLACK_TEMPLATE_ID,
    SlackDestinationInput,
    buildAlertCreatePayload,
    buildAlertDestinationPayload,
    buildErrorAlertHogFunctionPayload,
    buildScoutCreatePayload,
    buildSubscriptionCreatePayload,
} from './suggestionPayloads'

export interface AcceptedSuggestion {
    url: string
    /** False when the created thing exists but its Slack destination request failed after it. */
    slackConnected: boolean
}

export interface AcceptOutcome {
    accepted: AcceptedSuggestion
    /** What the kind created, for the accepted event. */
    eventProperties: Record<string, unknown>
}

export interface AcceptInput {
    suggestion: TurnSuggestion
    projectId: number
    userId: number | undefined
    slackIntegrationId: number | null
    slackChannel: string | null
    cadence: ScoutSuggestionCadence
    scoutBody: string
    direction: AlertSuggestionDirection
    changePercent: number
    notebookTitle: string
    conversationBlocks: ConversationBlocks
}

function slackDestination(input: AcceptInput): SlackDestinationInput {
    if (input.slackIntegrationId === null || !input.slackChannel) {
        throw new Error('Choose a Slack channel first')
    }
    return { slackIntegrationId: input.slackIntegrationId, slackChannel: input.slackChannel }
}

async function resolveInsightId(insightId: number | null, shortId: string): Promise<number> {
    const resolved = insightId ?? (await getInsightId(shortId as InsightShortId))
    if (resolved === undefined) {
        throw new Error('The saved insight could not be found')
    }
    return resolved
}

/** Creates what the card offers; the button's disabled reason keeps the inputs each kind needs in place before this runs. */
export async function acceptSuggestion(input: AcceptInput): Promise<AcceptOutcome> {
    const { suggestion, cadence } = input
    const projectId = String(input.projectId)
    switch (suggestion.kind) {
        case 'scout': {
            const created = await signalsScoutCreate(
                projectId,
                buildScoutCreatePayload({ suggestion, cadence, body: input.scoutBody, ...slackDestination(input) })
            )
            return {
                accepted: { url: urls.inboxScout(created.skill.name), slackConnected: true },
                eventProperties: { cadence, scout_mode: suggestion.scout.mode, scout_skill_name: created.skill.name },
            }
        }
        case 'notebook': {
            const blocks = input.conversationBlocks
            const notebook = buildConversationNotebook({
                title: input.notebookTitle,
                summary: suggestion.notebook.summary,
                blocks: blocks.blocks,
                incident: suggestion.notebook.incident,
            })
            const saved = await notebooksCreate(projectId, {
                title: input.notebookTitle.trim(),
                content: notebook.content,
                text_content: notebook.markdown,
            })
            return {
                accepted: { url: urls.notebook(saved.short_id), slackConnected: true },
                eventProperties: {
                    notebook_short_id: saved.short_id,
                    incident: suggestion.notebook.incident !== null,
                    message_count: blocks.messageCount,
                    query_count: blocks.queryCount,
                },
            }
        }
        case 'alert': {
            if (input.userId === undefined) {
                throw new Error('Your account is still loading')
            }
            const slack = slackDestination(input)
            const insightId = await resolveInsightId(suggestion.alert.insightId, suggestion.alert.insightShortId)
            const alert = await alertsCreate(
                projectId,
                buildAlertCreatePayload({
                    suggestion,
                    direction: input.direction,
                    changePercent: input.changePercent,
                    insightId,
                    userId: input.userId,
                })
            )
            let slackConnected = true
            try {
                await alertsDestinationsCreate(projectId, alert.id, buildAlertDestinationPayload(slack))
            } catch {
                // The alert exists, so the card reports it and points at where to add the channel.
                slackConnected = false
            }
            return {
                accepted: { url: urls.alert(alert.id), slackConnected },
                eventProperties: {
                    direction: input.direction,
                    change_percent: input.changePercent,
                    slack_connected: slackConnected,
                },
            }
        }
        case 'subscription': {
            const slack = slackDestination(input)
            const insightId = await resolveInsightId(
                suggestion.subscription.insightId,
                suggestion.subscription.insightShortId
            )
            const created = await subscriptionsCreate(
                projectId,
                buildSubscriptionCreatePayload({ suggestion, cadence, insightId, ...slack })
            )
            return {
                accepted: {
                    url: urls.insightSubcription(
                        suggestion.subscription.insightShortId as InsightShortId,
                        String(created.id)
                    ),
                    slackConnected: true,
                },
                eventProperties: { cadence, subscription_id: created.id },
            }
        }
        case 'error_alert': {
            const slack = slackDestination(input)
            const template = await hogFunctionTemplatesRetrieve(projectId, ERROR_ALERT_SLACK_TEMPLATE_ID)
            const created = await hogFunctionsCreate(
                projectId,
                buildErrorAlertHogFunctionPayload({
                    suggestion,
                    ...slack,
                    inputsSchema: template.inputs_schema as CyclotronJobInputSchemaType[] | null,
                })
            )
            return {
                accepted: { url: urls.errorTrackingAlert(created.id), slackConnected: true },
                eventProperties: { hog_function_id: created.id },
            }
        }
    }
}
