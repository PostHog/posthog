import { useActions, useValues } from 'kea'

import { SlackDestinationPicker } from 'lib/components/Comments/SlackDestinationPicker'

import { slackDestinationLogic } from '../logics/slackDestinationLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'

export interface SlackDestinationSectionProps extends TurnSuggestionLogicProps {
    /** What connecting Slack buys the user on this card, shown when the project has no workspace yet. */
    connectHint: string
}

export function SlackDestinationSection({ connectHint, ...logicProps }: SlackDestinationSectionProps): JSX.Element {
    const logic = slackDestinationLogic(logicProps)
    const { slackIntegrationId, slackChannel } = useValues(logic)
    const { setSlackIntegrationId, setSlackChannel, connectSlackClicked } = useActions(logic)

    return (
        <SlackDestinationPicker
            integrationId={slackIntegrationId}
            channel={slackChannel}
            onIntegrationChange={setSlackIntegrationId}
            onChannelChange={setSlackChannel}
            notConfiguredDescription={connectHint}
            onConnectClick={connectSlackClicked}
        />
    )
}
