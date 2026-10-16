import { LemonBanner, LemonCollapse, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type {
    ContentAutopilotValidationCheckApi,
    ContentAutopilotValidationReportApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

export interface ContentAutopilotValidationSummaryProps {
    report: ContentAutopilotValidationReportApi
}

const CheckList = ({ checks }: { checks: ContentAutopilotValidationCheckApi[] }): JSX.Element => (
    <ul className="m-0 mt-2 pl-5 list-disc">
        {checks.map((check) => (
            <li key={check.check_key}>
                <span className="font-semibold">{check.label}:</span> {check.message}
            </li>
        ))}
    </ul>
)

const checkTag = (check: ContentAutopilotValidationCheckApi): { type: LemonTagType; label: string } =>
    check.passed
        ? { type: 'success', label: 'Passed' }
        : check.blocking
          ? { type: 'danger', label: 'Must fix' }
          : { type: 'warning', label: 'Review' }

export const ContentAutopilotValidationSummary = ({ report }: ContentAutopilotValidationSummaryProps): JSX.Element => {
    const generationFailure = report.checks.find(({ check_key, passed }) => check_key === 'generation' && !passed)
    if (generationFailure) {
        return <LemonBanner type="error">This draft couldn't be written. {generationFailure.message}</LemonBanner>
    }

    const blocked = report.checks.filter(({ passed, blocking }) => !passed && blocking)
    const toReview = report.checks.filter(({ passed, blocking }) => !passed && !blocking)

    return (
        <div className="flex flex-col gap-2">
            {blocked.length > 0 ? (
                <LemonBanner type="error">
                    Fix {pluralize(blocked.length, 'check')} before you can download this draft. Edit it, or regenerate
                    it.
                    <CheckList checks={blocked} />
                </LemonBanner>
            ) : report.passed && report.checks.length > 0 ? (
                <LemonBanner type="success">
                    Ready to download. {pluralize(report.checks.filter(({ passed }) => passed).length, 'check')} passed.
                </LemonBanner>
            ) : (
                <LemonBanner type="info">
                    This draft hasn't been checked yet. Checks run after the draft is written.
                </LemonBanner>
            )}
            {toReview.length > 0 ? (
                <LemonBanner type="warning">
                    Worth a look before you publish:
                    <CheckList checks={toReview} />
                </LemonBanner>
            ) : null}
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'checks',
                        header: `All checks (${report.checks.length})`,
                        content: (
                            <div className="@container">
                                <div className="grid grid-cols-1 @xl:grid-cols-2 gap-2">
                                    {report.checks.map((check) => {
                                        const tag = checkTag(check)
                                        return (
                                            <div key={check.check_key} className="rounded border p-3">
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="font-semibold">{check.label}</span>
                                                    <LemonTag type={tag.type}>{tag.label}</LemonTag>
                                                </div>
                                                <div className="text-sm mt-1 text-muted">{check.message}</div>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
