import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { AgentSetupButton } from '../components/AgentSetupButton'
import { BigAction } from '../components/BigAction'
import { DnsHostLink } from '../components/DnsHostLink'
import { DnsRecordRows, RECORD_KIND_LABEL } from '../components/DnsRecordRows'
import { StepHeading } from '../components/StepHeading'
import { VerificationStepsStrip } from '../components/VerificationStepsStrip'
import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'
import { emailDomainLogic } from '../emailDomainLogic'
import { emailDomainManualSetupLogic } from '../emailDomainManualSetupLogic'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'
import { HedgehogHourglass, HedgehogPanic } from '../hoggies'

function Heading(): JSX.Element {
    const { status, pollingStopped, missingRecords, foundCount, records } = useValues(emailDomainStatusLogic)
    const { hostName } = useValues(emailDomainAutoConfigureLogic)
    const { recordsAdded } = useValues(emailDomainManualSetupLogic)
    const host = hostName ?? 'your DNS host'
    if (status?.status === 'failed') {
        return (
            <StepHeading
                Hoggie={HedgehogPanic}
                title="Verification stopped"
                lead="The email provider gave up waiting for the settings. Check them once more, then restart verification."
            />
        )
    }
    if (pollingStopped) {
        const missing = missingRecords.length
        return (
            <StepHeading
                Hoggie={HedgehogPanic}
                title={missing === 1 ? 'One setting is still missing' : `${missing} settings are still missing`}
                lead={`We found ${foundCount} of ${records.length}. Check the highlighted ones at ${host}, then check again.`}
            />
        )
    }
    return (
        <StepHeading
            Hoggie={HedgehogHourglass}
            busy
            title="Checking your settings…"
            lead={
                recordsAdded
                    ? 'DNS changes can take a few minutes to show up. You can leave this page and come back.'
                    : 'Some settings are already in place. We keep checking while this page is open.'
            }
        />
    )
}

function SecondaryActions(): JSX.Element {
    return (
        <div className="flex flex-wrap justify-center gap-1">
            <AgentSetupButton />
            <DnsHostLink />
        </div>
    )
}

function Actions(): JSX.Element {
    const { status, pollingStopped, statusLoading, restartResultLoading } = useValues(emailDomainStatusLogic)
    const { checkAgain, restartVerification } = useActions(emailDomainStatusLogic)
    if (status?.status === 'failed') {
        return (
            <div className="flex flex-col items-center gap-2">
                <BigAction
                    icon={<IconRefresh />}
                    onClick={restartVerification}
                    loading={restartResultLoading}
                    disabledReason={restartResultLoading ? 'Restarting' : undefined}
                    data-attr="email-domain-restart-verification"
                >
                    Restart verification
                </BigAction>
                <SecondaryActions />
            </div>
        )
    }
    if (pollingStopped) {
        return (
            <div className="flex flex-col items-center gap-2">
                <LemonBanner type="warning" className="w-full">
                    Still waiting on DNS. We stopped checking automatically, so check again once you have added the
                    missing settings.
                </LemonBanner>
                <BigAction
                    icon={<IconRefresh />}
                    onClick={checkAgain}
                    loading={statusLoading}
                    disabledReason={statusLoading ? 'Checking' : undefined}
                    data-attr="email-domain-check-again"
                >
                    Check again
                </BigAction>
                <SecondaryActions />
            </div>
        )
    }
    return <SecondaryActions />
}

export function VerifyingStep(): JSX.Element {
    const { status, pollingStopped, missingRecords, foundCount, records } = useValues(emailDomainStatusLogic)
    const { verificationSteps } = useValues(emailDomainLogic)
    const stuck = pollingStopped || status?.status === 'failed'
    const temporaryFailure = status?.status === 'temporary_failure'
    return (
        <div className="flex flex-col gap-8">
            <Heading />
            <div className="flex flex-col gap-2">
                <LemonProgress
                    percent={records.length ? (foundCount / records.length) * 100 : 0}
                    size="large"
                    strokeColor={stuck ? 'var(--danger)' : 'var(--success)'}
                    bgColor="var(--border-primary)"
                />
                <span className="text-sm text-secondary text-center">
                    {foundCount} of {records.length} found
                </span>
            </div>
            <VerificationStepsStrip steps={verificationSteps} />
            {temporaryFailure && (
                <LemonBanner type="error">
                    The email provider could not find these settings:{' '}
                    {missingRecords.map((record) => RECORD_KIND_LABEL[record.kind]).join(', ') || 'some of them'}. Check
                    them at your DNS host. We keep checking.
                </LemonBanner>
            )}
            <Actions />
            <DnsRecordRows records={records} missing={missingRecords} showStatus />
        </div>
    )
}
