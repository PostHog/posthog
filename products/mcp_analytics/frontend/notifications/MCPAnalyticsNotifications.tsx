import { NotificationsPane } from 'scenes/hog-functions/list/NotificationsPane'
import { urls } from 'scenes/urls'

import { Card } from '../dashboard/Card'

/**
 * The Notifications tab: use-case-first destinations for MCP events, built on
 * CDP hog function sub-templates (same chassis as survey response
 * notifications). Pick what you care about; the dialog handles the channel
 * (Slack, Teams, Discord, webhook) with MCP-tailored prefilled messages. The
 * end state we want: owners hear about these moments in the tools they already
 * live in, without ever needing to open a dashboard.
 */
export function MCPAnalyticsNotifications(): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-notifications">
            <Card title="Agents asked for something your server can't do">
                <NotificationsPane
                    subTemplateId="mcp-missing-capability"
                    type="destination"
                    requiredFeature={null}
                    description="Agents report what they searched for and couldn't find, delivered as your MCP roadmap wherever your team works."
                    dialogTitle="Notify me about missing capabilities"
                    returnTo={urls.mcpAnalyticsNotifications()}
                />
            </Card>
            <Card title="A tool call failed">
                <NotificationsPane
                    subTemplateId="mcp-tool-error"
                    type="destination"
                    requiredFeature={null}
                    description="Know the moment agents hit an error on one of your tools, with the agent's intent and a link to the tool's detail page."
                    dialogTitle="Notify me about failing tool calls"
                    returnTo={urls.mcpAnalyticsNotifications()}
                />
            </Card>
        </div>
    )
}
