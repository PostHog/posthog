import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { Skeleton } from '@posthog/quill'

import { QuillConfigurationSubsection } from '../QuillConfigurationSubsection'
import { issueRateLimitConfigLogic } from './issueRateLimitConfigLogic'
import { QuillIssueRateLimitList } from './QuillIssueRateLimitList'
import { QuillIssueRateLimitPreview } from './QuillIssueRateLimitPreview'
import { QuillRateLimitConfigFields } from './QuillRateLimitConfigFields'

export function QuillIssueRateLimitSettings(): JSX.Element {
    const { configLoading, configFormChanged, isConfigFormSubmitting } = useValues(issueRateLimitConfigLogic)

    if (configLoading) {
        return (
            <div className="flex flex-col gap-4">
                <Skeleton className="w-full h-10" />
                <Skeleton className="w-full h-64" />
            </div>
        )
    }

    return (
        <QuillConfigurationSubsection
            title="Per-issue rate limit"
            description="This limit applies to each issue per window. Once an issue exceeds the configured rate, further exceptions for it are dropped at ingestion."
        >
            <Form logic={issueRateLimitConfigLogic} formKey="configForm" enableFormOnSubmit className="@container">
                <div className="grid grid-cols-1 gap-6 @3xl:grid-cols-10">
                    <div className="@3xl:col-span-3">
                        <QuillRateLimitConfigFields
                            valueFieldName="per_issue_rate_limit_value"
                            bucketFieldName="per_issue_rate_limit_bucket_size_minutes"
                            valueDataAttr="issue-rate-limit-value"
                            bucketDataAttr="issue-rate-limit-bucket-size"
                            formChanged={configFormChanged}
                            formSubmitting={isConfigFormSubmitting}
                        />
                    </div>
                    <div className="@3xl:col-span-3">
                        <QuillIssueRateLimitList />
                    </div>
                    <div className="@3xl:col-span-4">
                        <QuillIssueRateLimitPreview />
                    </div>
                </div>
            </Form>
        </QuillConfigurationSubsection>
    )
}
