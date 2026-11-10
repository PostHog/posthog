import { useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { ComingSoonInterestLogicProps } from './comingSoonInterestLogic'

export type ComingSoonInterestSurvey = Omit<ComingSoonInterestLogicProps, 'accountId'>

export function useComingSoonInterestSurvey(survey: ComingSoonInterestSurvey): ComingSoonInterestLogicProps {
    const { user } = useValues(userLogic)
    return { ...survey, accountId: user?.uuid ?? '' }
}
