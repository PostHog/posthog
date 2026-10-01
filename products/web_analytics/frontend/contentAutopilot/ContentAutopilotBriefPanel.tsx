import type {
    ContentAutopilotBriefApi,
    ContentAutopilotEvidenceApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

export interface ContentAutopilotBriefPanelProps {
    brief: ContentAutopilotBriefApi
    evidence: ContentAutopilotEvidenceApi[]
}

const BriefList = ({ title, items }: { title: string; items?: string[] }): JSX.Element | null =>
    items && items.length > 0 ? (
        <section>
            <h4 className="mb-1">{title}</h4>
            <ul className="list-disc pl-5 m-0">
                {items.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                ))}
            </ul>
        </section>
    ) : null

const BriefText = ({ title, text }: { title: string; text?: string }): JSX.Element | null =>
    text ? (
        <section>
            <h4 className="mb-1">{title}</h4>
            <p className="m-0 text-sm">{text}</p>
        </section>
    ) : null

const BriefCard = ({ title, text }: { title: string; text?: string }): JSX.Element | null =>
    text ? (
        <div className="rounded border p-3">
            <div className="font-semibold">{title}</div>
            <div className="text-sm mt-1">{text}</div>
        </div>
    ) : null

export const ContentAutopilotBriefPanel = ({ brief, evidence }: ContentAutopilotBriefPanelProps): JSX.Element => {
    const reasons = evidence.map(({ explanation }) => explanation).filter(Boolean)
    const briefSaved = Boolean(brief.intent || brief.outline?.length)

    return (
        <div className="@container flex flex-col gap-4">
            <BriefList title="Why this was picked" items={reasons} />
            {briefSaved ? null : <p className="text-muted m-0">No brief was saved for this draft.</p>}
            <BriefText title="What the question means" text={brief.disambiguation} />
            <div className="grid grid-cols-1 @md:grid-cols-2 gap-3">
                <BriefCard title="What the reader wants" text={brief.intent} />
                <BriefCard title="Audience" text={brief.audience} />
            </div>
            <BriefText title="What AI assistants say today" text={brief.engine_answer_summary} />
            <BriefList title="Outline" items={brief.outline} />
            <BriefList title="Questions to answer" items={brief.questions_to_answer} />
            <BriefList title="Covered by cited pages but not by this site" items={brief.competitor_coverage} />
        </div>
    )
}
