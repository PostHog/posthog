import { AnalyticsAnomalyInvestigationSignalCard } from './AnalyticsAnomalyInvestigationSignalCard'
import { ConversationsTicketSignalCard } from './ConversationsTicketSignalCard'
import { EndpointExecutionFailedSignalCard } from './EndpointExecutionFailedSignalCard'
import { EngineeringAnalyticsSignalCard } from './EngineeringAnalyticsSignalCard'
import { ErrorTrackingSignalCard } from './ErrorTrackingSignalCard'
import { GithubIssueSignalCard } from './GithubIssueSignalCard'
import { HealthCheckSignalCard } from './HealthCheckSignalCard'
import { LinearIssueSignalCard } from './LinearIssueSignalCard'
import { LlmEvalReportSignalCard, LlmEvalTraceSignalCard } from './LlmAnalyticsSignalCard'
import { LogsAlertSignalCard } from './LogsAlertSignalCard'
import { PgAnalyzeSignalCard } from './PgAnalyzeSignalCard'
import { ScannerFindingSignalCard } from './ScannerFindingSignalCard'
import { SessionReplaySignalCard } from './SessionReplaySignalCard'
import { SignalsScoutSignalCard } from './SignalsScoutSignalCard'
import type { SignalCardRegistry } from './types'
import { ZendeskTicketSignalCard } from './ZendeskTicketSignalCard'

/** The Lemon card for each matcher key in `SIGNAL_CARD_MATCHERS`, which owns the matching order. */
export const SIGNAL_CARD_REGISTRY: SignalCardRegistry = {
    error_tracking: ErrorTrackingSignalCard,
    session_replay: SessionReplaySignalCard,
    replay_vision: ScannerFindingSignalCard,
    'llm_analytics:evaluation_report': LlmEvalReportSignalCard,
    'llm_analytics:evaluation': LlmEvalTraceSignalCard,
    health_checks: HealthCheckSignalCard,
    conversations: ConversationsTicketSignalCard,
    endpoints: EndpointExecutionFailedSignalCard,
    engineering_analytics: EngineeringAnalyticsSignalCard,
    logs: LogsAlertSignalCard,
    analytics: AnalyticsAnomalyInvestigationSignalCard,
    signals_scout: SignalsScoutSignalCard,
    github: GithubIssueSignalCard,
    linear: LinearIssueSignalCard,
    zendesk: ZendeskTicketSignalCard,
    pganalyze: PgAnalyzeSignalCard,
}
