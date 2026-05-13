import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import type {
    Assumption,
    Competitor,
    Confidence,
    Differentiation,
    Risk,
    Severity,
    ValidationExperiment,
    ValidationReport,
    Verdict,
} from './founderValidationLogic'

// Confidence ranges high (good) → low (bad). Severity is inverted (high = danger).
const CONFIDENCE_TAG: Record<Confidence, LemonTagType> = {
    high: 'success',
    medium: 'warning',
    low: 'option',
}
const SEVERITY_TAG: Record<Severity, LemonTagType> = {
    high: 'danger',
    medium: 'warning',
    low: 'option',
}

function scoreTone(score: number): LemonTagType {
    if (score >= 8) {
        return 'success'
    }
    if (score >= 5) {
        return 'warning'
    }
    return 'danger'
}

export function ValidationReportView({ report }: { report: ValidationReport }): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <VerdictHero verdict={report.verdict} />
            <DifferentiationCard differentiation={report.differentiation} />
            <CompetitorsSection competitors={report.competitors} />
            <AssumptionsSection assumptions={report.assumptions} experiments={report.experiments} />
            <RisksSection risks={report.risks} />
        </div>
    )
}

function VerdictHero({ verdict }: { verdict: Verdict }): JSX.Element {
    return (
        <LemonCard className="p-6">
            <div className="flex items-start gap-6">
                <div className="flex flex-col items-center">
                    <span className="text-xs uppercase tracking-wide text-text-secondary">Score</span>
                    <span className="text-5xl font-semibold leading-none mt-1">{verdict.score}</span>
                    <span className="text-xs text-text-secondary mt-1">/ 10</span>
                    <LemonTag type={scoreTone(verdict.score)} className="mt-2">
                        {verdict.confidence} confidence
                    </LemonTag>
                </div>
                <div className="flex-1">
                    <h2 className="text-lg font-medium">Verdict</h2>
                    <p className="text-sm text-text-secondary mt-2 leading-relaxed">{verdict.reasoning}</p>
                    {verdict.next_steps.length > 0 && (
                        <>
                            <h3 className="text-sm font-medium mt-4">Recommended next steps</h3>
                            <ol className="list-decimal pl-5 mt-2 text-sm text-text-secondary space-y-1">
                                {verdict.next_steps.map((step, i) => (
                                    <li key={i}>{step}</li>
                                ))}
                            </ol>
                        </>
                    )}
                </div>
            </div>
        </LemonCard>
    )
}

function DifferentiationCard({ differentiation }: { differentiation: Differentiation }): JSX.Element {
    return (
        <LemonCard className="p-6">
            <h2 className="text-lg font-medium">Differentiation</h2>
            <dl className="grid sm:grid-cols-3 gap-4 mt-4 text-sm">
                <DifferentiationField label="Positioning" value={differentiation.summary} />
                <DifferentiationField label="Moat" value={differentiation.moat} />
                <DifferentiationField label="Gap in market" value={differentiation.gap_in_market} />
            </dl>
        </LemonCard>
    )
}

function DifferentiationField({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div>
            <dt className="text-xs uppercase tracking-wide text-text-secondary">{label}</dt>
            <dd className="mt-1 text-text-primary">{value}</dd>
        </div>
    )
}

function CompetitorsSection({ competitors }: { competitors: Competitor[] }): JSX.Element {
    return (
        <LemonCard className="p-6">
            <h2 className="text-lg font-medium">Competitors</h2>
            <div className="grid md:grid-cols-2 gap-4 mt-4">
                {competitors.map((c, i) => (
                    <div key={i} className="border border-border rounded-md p-4">
                        <div className="flex items-baseline justify-between gap-2">
                            <h3 className="text-base font-medium">{c.name}</h3>
                            {c.pricing && <span className="text-xs text-text-secondary">{c.pricing}</span>}
                        </div>
                        <p className="text-sm text-text-secondary mt-1">{c.description}</p>
                        <p className="text-xs text-text-secondary mt-2">
                            <span className="font-medium">Positioning:</span> {c.positioning}
                        </p>
                        <div className="grid grid-cols-2 gap-3 mt-3 text-xs">
                            <div>
                                <span className="font-medium">Strengths</span>
                                <ul className="list-disc pl-4 mt-1 text-text-secondary space-y-0.5">
                                    {c.strengths.map((s, j) => (
                                        <li key={j}>{s}</li>
                                    ))}
                                </ul>
                            </div>
                            <div>
                                <span className="font-medium">Weaknesses</span>
                                <ul className="list-disc pl-4 mt-1 text-text-secondary space-y-0.5">
                                    {c.weaknesses.map((w, j) => (
                                        <li key={j}>{w}</li>
                                    ))}
                                </ul>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </LemonCard>
    )
}

function AssumptionsSection({
    assumptions,
    experiments,
}: {
    assumptions: Assumption[]
    experiments: ValidationExperiment[]
}): JSX.Element {
    // Pre-bucket experiments by the assumption they validate so we can pair them inline.
    // A single assumption may have multiple experiments (or none).
    const experimentsByAssumption = new Map<number, ValidationExperiment[]>()
    experiments.forEach((exp) => {
        const list = experimentsByAssumption.get(exp.assumption_index) ?? []
        list.push(exp)
        experimentsByAssumption.set(exp.assumption_index, list)
    })

    return (
        <LemonCard className="p-6">
            <h2 className="text-lg font-medium">Critical assumptions</h2>
            <p className="text-xs text-text-secondary mt-1">
                Ordered by riskiness — the assumption most likely to kill this idea is first.
            </p>
            <ol className="mt-4 space-y-4">
                {assumptions.map((a, i) => (
                    <li key={i} className="border-l-2 border-border pl-4">
                        <div className="flex items-baseline gap-2">
                            <span className="text-sm font-medium">{i + 1}.</span>
                            <p className="text-sm">{a.statement}</p>
                            <LemonTag type={CONFIDENCE_TAG[a.current_confidence]} className="ml-auto">
                                {a.current_confidence}
                            </LemonTag>
                        </div>
                        <p className="text-xs text-text-secondary mt-1">
                            <span className="font-medium">If false:</span> {a.risk_if_false}
                        </p>
                        {(experimentsByAssumption.get(i) ?? []).map((exp, j) => (
                            <div key={j} className="mt-3 ml-4 p-3 bg-bg-3000 rounded-md">
                                <div className="flex items-baseline justify-between gap-2">
                                    <h4 className="text-sm font-medium">Experiment: {exp.name}</h4>
                                    <span className="text-xs text-text-secondary">{exp.cost_estimate}</span>
                                </div>
                                <p className="text-xs text-text-secondary mt-1">{exp.description}</p>
                                <p className="text-xs mt-1">
                                    <span className="font-medium">Success signal:</span> {exp.success_signal}
                                </p>
                            </div>
                        ))}
                    </li>
                ))}
            </ol>
        </LemonCard>
    )
}

function RisksSection({ risks }: { risks: Risk[] }): JSX.Element {
    return (
        <LemonCard className="p-6">
            <h2 className="text-lg font-medium">Risks</h2>
            <ul className="mt-4 space-y-3">
                {risks.map((r, i) => (
                    <li key={i} className="flex items-baseline gap-3">
                        <LemonTag type={SEVERITY_TAG[r.severity]}>{r.severity}</LemonTag>
                        <span className="text-xs uppercase tracking-wide text-text-secondary">{r.category}</span>
                        <span className="text-sm flex-1">{r.description}</span>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}
