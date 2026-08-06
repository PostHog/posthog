import { IconChevronDown } from '@posthog/icons'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

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

    const intentLabel =
        status === 'active' ? ISSUE_STATUS_CONFIG.resolved.intentLabel : ISSUE_STATUS_CONFIG.active.intentLabel

    return (
        <>
            <HogfettiComponent />
            <span data-quill className="contents">
                <ButtonGroup>
                    <Tooltip>
                        <TooltipTrigger render={<Button variant="primary" size="default" onClick={handleResolve} />}>
                            {status === 'active' ? 'Resolve' : 'Reopen'}
                        </TooltipTrigger>
                        <TooltipContent>{intentLabel}</TooltipContent>
                    </Tooltip>
                    {status === 'active' && (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        variant="primary"
                                        size="icon"
                                        aria-label={ISSUE_STATUS_CONFIG.suppressed.intentLabel}
                                    />
                                }
                            >
                                <IconChevronDown />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-auto min-w-32">
                                <DropdownMenuItem onClick={() => onChange('suppressed')}>Suppress</DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </ButtonGroup>
            </span>
        </>
    )
}
