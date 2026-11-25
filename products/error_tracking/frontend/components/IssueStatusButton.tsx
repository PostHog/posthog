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

import type { ResolvedUntilEnumApi } from '../generated/api.schemas'
import { ISSUE_STATUS_CONFIG } from './Indicators'
import { RESOLVE_MODES } from './resolveModes'

export const IssueStatusButton = ({
    status,
    onChange,
    loading = false,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status'], resolvedUntil?: ResolvedUntilEnumApi) => void
    loading?: boolean
}): JSX.Element => {
    const { trigger, HogfettiComponent } = useHogfetti()
    const [plainResolve] = RESOLVE_MODES

    const resolve = (resolvedUntil: ResolvedUntilEnumApi): void => {
        onChange('resolved', resolvedUntil)
        ;[0, 400, 800].forEach((delay) => setTimeout(trigger, delay))
    }

    return (
        <>
            <HogfettiComponent />
            {status === 'active' ? (
                <ButtonGroup>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="primary"
                                    className="[translate:0_0]"
                                    onClick={() => resolve(plainResolve.value)}
                                    loading={loading}
                                    data-attr="error-tracking-resolve"
                                >
                                    {plainResolve.action}
                                </Button>
                            }
                        />
                        <TooltipContent>{plainResolve.description}</TooltipContent>
                    </Tooltip>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="primary"
                                    size="icon"
                                    disabled={loading}
                                    aria-label="More ways to resolve"
                                    data-attr="error-tracking-resolve-options"
                                />
                            }
                        >
                            <IconChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {RESOLVE_MODES.map((mode) => (
                                <DropdownMenuItem
                                    key={mode.value}
                                    description={mode.description}
                                    onClick={() => resolve(mode.value)}
                                    data-attr={`error-tracking-resolve-until-${mode.value.replace('_', '-')}`}
                                >
                                    {mode.action}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </ButtonGroup>
            ) : (
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="primary"
                                className="[translate:0_0]"
                                onClick={() => onChange('active')}
                                loading={loading}
                                data-attr="error-tracking-resolve"
                            >
                                Reopen
                            </Button>
                        }
                    />
                    <TooltipContent>{ISSUE_STATUS_CONFIG.active.intentLabel}</TooltipContent>
                </Tooltip>
            )}
        </>
    )
}
