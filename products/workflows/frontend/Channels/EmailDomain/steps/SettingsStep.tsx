import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AgentSetupButton } from '../components/AgentSetupButton'
import { BigAction } from '../components/BigAction'
import { DnsHostLink } from '../components/DnsHostLink'
import { DnsRecordRows } from '../components/DnsRecordRows'
import { StepHeading } from '../components/StepHeading'
import { VerificationStepsStrip } from '../components/VerificationStepsStrip'
import { dnsHostGotcha } from '../dnsHosts'
import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'
import { emailDomainLogic } from '../emailDomainLogic'
import { emailDomainManualSetupLogic } from '../emailDomainManualSetupLogic'
import { emailDomainSenderLogic } from '../emailDomainSenderLogic'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'
import { HedgehogMagnifyingGlass, HedgehogWizard } from '../hoggies'

const RECORDS_EXPLAINER =
    'Each setting is a DNS record. Add them exactly as shown, name and value, and keep the rest of your DNS as it is.'

function Gotcha(): JSX.Element {
    const { hostName } = useValues(emailDomainAutoConfigureLogic)
    return <p className="m-0 text-sm text-secondary text-center text-balance">Heads up: {dnsHostGotcha(hostName)}</p>
}

function AddedThemButton({ primary }: { primary?: boolean }): JSX.Element {
    const { statusLoading } = useValues(emailDomainStatusLogic)
    const { markRecordsAdded } = useActions(emailDomainManualSetupLogic)
    const Button = primary ? BigAction : LemonButton
    return (
        <Button
            type={primary ? 'primary' : 'secondary'}
            onClick={markRecordsAdded}
            loading={statusLoading}
            disabledReason={statusLoading ? 'Checking' : undefined}
            data-attr="email-domain-records-added"
        >
            I've added them
        </Button>
    )
}

function AutoConfigureChoice(): JSX.Element {
    const { hostName, autoConfigureLoading } = useValues(emailDomainAutoConfigureLogic)
    const { openAutoConfigure } = useActions(emailDomainAutoConfigureLogic)
    const { recordsRevealed } = useValues(emailDomainManualSetupLogic)
    const { revealRecords } = useActions(emailDomainManualSetupLogic)
    const { records } = useValues(emailDomainStatusLogic)
    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-col items-center gap-2">
                <BigAction
                    onClick={openAutoConfigure}
                    loading={autoConfigureLoading}
                    disabledReason={autoConfigureLoading ? 'Opening' : undefined}
                    data-attr="email-domain-auto-configure"
                >
                    Add them to {hostName} for me
                </BigAction>
                <span className="text-xs text-secondary">You approve it once in {hostName}. Nothing else changes.</span>
                <div className="flex flex-wrap justify-center gap-1">
                    {!recordsRevealed && (
                        <LemonButton type="tertiary" onClick={revealRecords} data-attr="email-domain-reveal-records">
                            I'll add them myself
                        </LemonButton>
                    )}
                    <AgentSetupButton />
                </div>
            </div>
            {recordsRevealed && (
                <div className="flex flex-col gap-3">
                    <p className="m-0 text-sm text-secondary text-center">{RECORDS_EXPLAINER}</p>
                    <DnsRecordRows records={records} showStatus />
                    <Gotcha />
                    <div className="flex flex-wrap justify-center gap-1">
                        <DnsHostLink />
                        <AddedThemButton />
                    </div>
                </div>
            )}
        </div>
    )
}

function ManualChoice(): JSX.Element {
    const { dnsHost } = useValues(emailDomainAutoConfigureLogic)
    const { records } = useValues(emailDomainStatusLogic)
    return (
        <div className="flex flex-col gap-5">
            <div className="flex flex-col items-center gap-2">
                {dnsHost ? (
                    <>
                        <DnsHostLink primary />
                        <AddedThemButton />
                    </>
                ) : (
                    <AddedThemButton primary />
                )}
                <AgentSetupButton />
            </div>
            <Gotcha />
            <p className="m-0 text-sm text-secondary text-center">{RECORDS_EXPLAINER}</p>
            <DnsRecordRows records={records} showStatus />
        </div>
    )
}

function NoRecordsYet(): JSX.Element {
    const { restartResultLoading } = useValues(emailDomainStatusLogic)
    const { restartVerification } = useActions(emailDomainStatusLogic)
    return (
        <div className="flex flex-col items-center gap-2">
            <p className="m-0 text-sm text-secondary text-center">
                The email provider has not handed out your settings yet. Start verification to get them.
            </p>
            <BigAction
                icon={<IconRefresh />}
                onClick={restartVerification}
                loading={restartResultLoading}
                disabledReason={restartResultLoading ? 'Starting' : undefined}
                data-attr="email-domain-start-verification"
            >
                Start verification
            </BigAction>
        </div>
    )
}

function FindingHost({ domain, count }: { domain: string | null; count: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-8">
            <StepHeading
                Hoggie={HedgehogMagnifyingGlass}
                busy
                title={`Finding where ${domain}'s DNS lives…`}
                lead="This tells us whether we can add the settings for you."
            />
            <BigAction disabledReason="Still finding your DNS host">
                {count ? `Add ${count} settings` : 'Get your settings'}
            </BigAction>
        </div>
    )
}

export function SettingsStep(): JSX.Element {
    const { domain } = useValues(emailDomainSenderLogic)
    const { detectionLoading, hostName, supportsDomainConnect } = useValues(emailDomainAutoConfigureLogic)
    const { records } = useValues(emailDomainStatusLogic)
    const { verificationSteps } = useValues(emailDomainLogic)
    const count = records.length
    const host = hostName ?? 'your DNS host'

    if (detectionLoading) {
        return <FindingHost domain={domain} count={count} />
    }

    const lead = supportsDomainConnect
        ? `${hostName} runs ${domain}'s DNS and lets PostHog add settings for you.`
        : hostName
          ? `${hostName} runs ${domain}'s DNS. Add these there, then come back.`
          : `We could not tell who runs ${domain}'s DNS. Open your DNS provider's settings and add these.`

    return (
        <div className="flex flex-col gap-8">
            <StepHeading
                Hoggie={HedgehogWizard}
                title={count ? `Add ${count} settings at ${host}` : 'Get your settings from the email provider'}
                lead={lead}
            />
            {count === 0 ? <NoRecordsYet /> : supportsDomainConnect ? <AutoConfigureChoice /> : <ManualChoice />}
            <div className="flex flex-col gap-2">
                <span className="text-xs text-secondary text-center uppercase tracking-wide">What happens next</span>
                <VerificationStepsStrip steps={verificationSteps} />
            </div>
        </div>
    )
}
