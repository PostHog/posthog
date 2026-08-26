import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ISSUE_STATUS_CONFIG } from './Indicators'

export const IssueStatusButton = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    const { trigger, HogfettiComponent } = useHogfetti()

    const handleResolve = (): void => {
        if (status === 'active') {
            onChange('resolved')
            ;[0, 400, 800].forEach((delay) => setTimeout(trigger, delay))
        } else {
            onChange('active')
        }
    }

    return (
        <>
            <HogfettiComponent />
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button variant="primary" onClick={handleResolve} data-attr="error-tracking-resolve">
                            {status === 'active' ? 'Resolve' : 'Reopen'}
                        </Button>
                    }
                />
                <TooltipContent>
                    {status === 'active'
                        ? ISSUE_STATUS_CONFIG.resolved.intentLabel
                        : ISSUE_STATUS_CONFIG.active.intentLabel}
                </TooltipContent>
            </Tooltip>
        </>
    )
}
