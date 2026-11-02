import './MissingCapabilitiesPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { type BrandMarkName } from '../brandMarks'
import { BrandMark } from '../components/BrandMark'

interface PreviewReport {
    /** The ask in the agent's own words. */
    ask: string
    client: string
    /** Omitted when the report arrived without a client. */
    mark?: BrandMarkName
    time: string
}

// These examples cover specific tool gaps and a report without client identity.
const REPORTS: PreviewReport[] = [
    {
        ask: 'Wanted to bulk-close 40 stale tickets but only single-ticket updates exist',
        client: 'Claude Code',
        mark: 'Claude',
        time: '2m ago',
    },
    {
        ask: 'Tried to find issues by assignee, but search_issues only takes free text',
        client: 'Cursor',
        mark: 'Cursor',
        time: '18m ago',
    },
    {
        ask: "Needed to attach the failing build log to the incident, there's no upload tool",
        client: 'Unknown client',
        time: '1h ago',
    },
    {
        ask: "User asked for last month's invoice PDF. I can list invoices, not fetch one",
        client: 'Codex',
        mark: 'OpenAI',
        time: '3h ago',
    },
    {
        ask: 'Had to roll back the bad deploy and only deploy and get_status are exposed',
        client: 'Windsurf',
        mark: 'Windsurf',
        time: 'Yesterday',
    },
]

/**
 * Example-data preview of the missing-capabilities feed, for the tab's empty state: what lands
 * here once agents start reporting. Static rows, no state, and the only motion is a CSS stagger
 * that settles after the initial render.
 */
export function MissingCapabilitiesPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('MissingCapsPreview', isStatic && 'MissingCapsPreview--static')}>
            <div className="MissingCapsPreview__head">
                <span className="MissingCapsPreview__title">Missing capabilities</span>
                <LemonTag size="small">example data</LemonTag>
            </div>

            <div className="MissingCapsPreview__rows">
                {REPORTS.map((report, i) => (
                    <div key={i} className="MissingCapsPreview__row">
                        <span className="MissingCapsPreview__ask">{report.ask}</span>
                        <span className="MissingCapsPreview__meta">
                            {report.mark ? (
                                <span className="MissingCapsPreview__client">
                                    <span className="MissingCapsPreview__logo">
                                        <BrandMark name={report.mark} className="size-2.5" />
                                    </span>
                                    {report.client}
                                </span>
                            ) : (
                                <span className="MissingCapsPreview__client MissingCapsPreview__client--unknown">
                                    <span className="MissingCapsPreview__logo MissingCapsPreview__logo--unknown" />
                                    {report.client}
                                </span>
                            )}
                            <span className="MissingCapsPreview__time">{report.time}</span>
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}
