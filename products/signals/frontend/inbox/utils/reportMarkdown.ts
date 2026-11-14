import type { SignalReport } from '../types'
import { displayConventionalCommitTitle } from './reportPresentation'

/** The report as markdown, for a person to paste into a document or into their own AI chat. */
export function reportMarkdown(report: Pick<SignalReport, 'title' | 'summary'>, reportUrl: string): string {
    const title = displayConventionalCommitTitle(report.title, 'Untitled report')
    return [`# ${title}`, report.summary?.trim(), `[Open the report in PostHog](${reportUrl})`]
        .filter(Boolean)
        .join('\n\n')
}
