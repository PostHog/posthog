import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NewSurvey } from 'scenes/surveys/constants'

import { Survey } from '~/types'

import { buildApiSurveySnippet } from 'products/surveys/frontend/apiSurveySnippet'

export function SurveyApiSnippet({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    return (
        <CodeSnippet wrap language={Language.JavaScript} compact>
            {buildApiSurveySnippet(survey)}
        </CodeSnippet>
    )
}
