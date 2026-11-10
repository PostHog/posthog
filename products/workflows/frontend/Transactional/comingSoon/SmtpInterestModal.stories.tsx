import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { comingSoonInterestLogic } from './comingSoonInterestLogic'
import { SmtpInterestModal } from './SmtpInterestModal'
import { SMTP_INTEREST_SURVEY } from './smtpInterestSurvey'
import { useComingSoonInterestSurvey } from './useComingSoonInterestSurvey'

const meta: Meta<typeof SmtpInterestModal> = {
    title: 'Scenes-App/Transactional/SMTP coming soon',
    component: SmtpInterestModal,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

function OpenedSmtpInterestModal(): JSX.Element {
    const { registerInterest } = useActions(comingSoonInterestLogic(useComingSoonInterestSurvey(SMTP_INTEREST_SURVEY)))
    useEffect(() => {
        registerInterest()
    }, [registerInterest])
    return <SmtpInterestModal />
}

export const NoteOpen: StoryObj<typeof SmtpInterestModal> = {
    render: () => <OpenedSmtpInterestModal />,
}
