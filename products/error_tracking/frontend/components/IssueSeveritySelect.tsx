import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { ISSUE_SEVERITY_OPTIONS, IssueSeverityTag, issueSeverityLabel, type IssueSeverity } from './IssueSeverityTag'

type IssueSeveritySelectProps = {
    severity: IssueSeverity | null | undefined
    onChange: (severity: IssueSeverity | null) => void
    loading?: boolean
}

export function IssueSeveritySelect({ severity, onChange, loading = false }: IssueSeveritySelectProps): JSX.Element {
    return (
        <LemonMenu
            placement="bottom-start"
            items={[
                ...ISSUE_SEVERITY_OPTIONS.map((option) => ({
                    active: severity === option.value,
                    label: <IssueSeverityTag severity={option.value} />,
                    onClick: () => {
                        if (severity !== option.value) {
                            onChange(option.value)
                        }
                    },
                })),
                {
                    active: !severity,
                    label: <IssueSeverityTag severity={null} />,
                    onClick: () => {
                        if (severity) {
                            onChange(null)
                        }
                    },
                },
            ]}
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                loading={loading}
                sideIcon={<IconChevronDown />}
                aria-label={`Severity: ${issueSeverityLabel(severity)}`}
                data-attr="error-tracking-issue-severity"
            >
                <IssueSeverityTag severity={severity} />
            </LemonButton>
        </LemonMenu>
    )
}
