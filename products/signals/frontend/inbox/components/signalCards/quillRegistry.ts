import { QuillAnalyticsAnomalyInvestigationSignalCard } from './QuillAnalyticsAnomalyInvestigationSignalCard'
import { QuillConversationsTicketSignalCard } from './QuillConversationsTicketSignalCard'
import { QuillEndpointExecutionFailedSignalCard } from './QuillEndpointExecutionFailedSignalCard'
import { QuillEngineeringAnalyticsSignalCard } from './QuillEngineeringAnalyticsSignalCard'
import { QuillErrorTrackingSignalCard } from './QuillErrorTrackingSignalCard'
import { QuillGithubIssueSignalCard } from './QuillGithubIssueSignalCard'
import { QuillHealthCheckSignalCard } from './QuillHealthCheckSignalCard'
import { QuillLinearIssueSignalCard } from './QuillLinearIssueSignalCard'
import { QuillLlmEvalReportSignalCard, QuillLlmEvalTraceSignalCard } from './QuillLlmAnalyticsSignalCard'
import { QuillLogsAlertSignalCard } from './QuillLogsAlertSignalCard'
import { QuillPgAnalyzeSignalCard } from './QuillPgAnalyzeSignalCard'
import { QuillScannerFindingSignalCard } from './QuillScannerFindingSignalCard'
import { QuillSessionReplaySignalCard } from './QuillSessionReplaySignalCard'
import { QuillSignalsScoutSignalCard } from './QuillSignalsScoutSignalCard'
import { QuillZendeskTicketSignalCard } from './QuillZendeskTicketSignalCard'
import type { SignalCardRegistry } from './types'

/** The quill card for each matcher key in `SIGNAL_CARD_MATCHERS`, which owns the matching order. */
export const QUILL_SIGNAL_CARD_REGISTRY: SignalCardRegistry = {
    error_tracking: QuillErrorTrackingSignalCard,
    session_replay: QuillSessionReplaySignalCard,
    replay_vision: QuillScannerFindingSignalCard,
    'llm_analytics:evaluation_report': QuillLlmEvalReportSignalCard,
    'llm_analytics:evaluation': QuillLlmEvalTraceSignalCard,
    health_checks: QuillHealthCheckSignalCard,
    conversations: QuillConversationsTicketSignalCard,
    endpoints: QuillEndpointExecutionFailedSignalCard,
    engineering_analytics: QuillEngineeringAnalyticsSignalCard,
    logs: QuillLogsAlertSignalCard,
    analytics: QuillAnalyticsAnomalyInvestigationSignalCard,
    signals_scout: QuillSignalsScoutSignalCard,
    github: QuillGithubIssueSignalCard,
    linear: QuillLinearIssueSignalCard,
    zendesk: QuillZendeskTicketSignalCard,
    pganalyze: QuillPgAnalyzeSignalCard,
}
