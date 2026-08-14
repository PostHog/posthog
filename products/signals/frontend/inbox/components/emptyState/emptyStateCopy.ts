import { SignalSourceType } from '../../types'

const SOURCE_TRIGGER_COPY: Partial<Record<SignalSourceType, string>> = {
    [SignalSourceType.SessionProblem]: 'a session shows a product problem',
    [SignalSourceType.Evaluation]: 'an AI evaluation fails',
    [SignalSourceType.EvaluationReport]: 'AI evaluation results need attention',
    [SignalSourceType.Issue]: 'a new issue arrives',
    [SignalSourceType.Ticket]: 'a support ticket arrives',
    [SignalSourceType.IssueCreated]: 'a new error appears',
    [SignalSourceType.IssueReopened]: 'a resolved error returns',
    [SignalSourceType.IssueSpiking]: 'an error starts spiking',
    [SignalSourceType.HealthIssue]: 'an instrumentation problem appears',
    [SignalSourceType.AnomalyInvestigation]: 'a product metric changes unexpectedly',
    [SignalSourceType.CiFlakyCheck]: 'a CI check becomes flaky',
    [SignalSourceType.CiBrokenDefaultBranch]: 'the default branch breaks',
    [SignalSourceType.CiDurationRegression]: 'a CI workflow slows down',
}

export function sourceTriggerCopy(sourceType: SignalSourceType): string {
    return SOURCE_TRIGGER_COPY[sourceType] ?? 'a new signal arrives'
}
