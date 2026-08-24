import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { AgentIssue } from './agentAnalyticsLogic'

export const agentIssueDemandLabel = (issue: AgentIssue): string => humanFriendlyLargeNumber(issue.demand)
