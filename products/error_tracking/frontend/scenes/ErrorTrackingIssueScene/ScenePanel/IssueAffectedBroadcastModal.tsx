import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import {
    AFFECTED_LOOKBACK_DAYS,
    IssueAffectedBroadcastLogicProps,
    issueAffectedBroadcastLogic,
} from './issueAffectedBroadcastLogic'

export function IssueAffectedBroadcastModal(props: IssueAffectedBroadcastLogicProps): JSX.Element {
    const logic = issueAffectedBroadcastLogic(props)
    const { isModalOpen, affectedCount, affectedCountLoading, countFailed, audienceCohortLoading } = useValues(logic)
    const { closeModal, createAudience } = useActions(logic)

    const lookback = `the last ${AFFECTED_LOOKBACK_DAYS} days`
    const disabledReason = affectedCountLoading
        ? 'Counting the people affected'
        : countFailed
          ? "Couldn't count the people affected"
          : !affectedCount?.people
            ? `Nobody hit this issue in ${lookback}`
            : !affectedCount.withEmail
              ? 'Nobody affected has an email address'
              : undefined

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title="Email the people affected"
            width={480}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createAudience}
                        loading={audienceCohortLoading}
                        disabledReason={disabledReason}
                        data-attr="issue-affected-broadcast-continue"
                    >
                        Continue to broadcast
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                {affectedCountLoading ? (
                    <div className="flex items-center gap-2">
                        <Spinner />
                        Counting the people affected
                    </div>
                ) : countFailed ? (
                    <p className="m-0">Couldn't count the people affected. Close this and try again.</p>
                ) : !affectedCount?.people ? (
                    <p className="m-0">Nobody hit this issue in {lookback}, so there is no one to email.</p>
                ) : !affectedCount.withEmail ? (
                    <p className="m-0">
                        <strong>{pluralize(affectedCount.people, 'person', 'people')}</strong> hit this issue in{' '}
                        {lookback}, but nobody affected has an email address, so there is no one to email.
                    </p>
                ) : (
                    <>
                        <p className="m-0">
                            <strong>{pluralize(affectedCount.people, 'person', 'people')}</strong> hit this issue in{' '}
                            {lookback}. {humanFriendlyNumber(affectedCount.withEmail)} of them{' '}
                            {pluralize(affectedCount.withEmail, 'has', 'have', false)} an email address. Only people
                            with an email address receive the broadcast.
                        </p>
                        <p className="m-0 text-secondary">
                            Continuing saves these people as a static cohort and opens a new broadcast to them.
                        </p>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
