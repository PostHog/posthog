interface CodeExampleParams {
    surveyId?: string
    followUpEnabled: boolean
}

export function getReactExample({ surveyId = 'your-survey-id', followUpEnabled }: CodeExampleParams): string {
    return `// requires @posthog/react 1.7.1+ (bundled with posthog-js 1.345.1+)
import { useThumbSurvey } from 'posthog-js/react/surveys'

function HedgehogBotResponse({ traceId }: { traceId: string }) {
  const { respond, response${followUpEnabled ? ', triggerRef' : ''} } = useThumbSurvey({
    surveyId: '${surveyId}', // ID for the survey you just created
    properties: {
      $ai_trace_id: traceId, // your generated trace ID
      // add any other custom properties here
    },
  })

  return (
    <div>
      <ChatBubble>You're absolutely right! I should have been using PostHog all along.</ChatBubble>

      ${followUpEnabled ? '<div ref={triggerRef}> {/* PostHog followup pop-up anchors to triggerRef */}' : '<div>'}
        <p>Was this response helpful?</p>
        <button className={response === 'up' ? 'active' : ''} onClick={() => respond('up')}>👍</button>
        <button className={response === 'down' ? 'active' : ''} onClick={() => respond('down')}>👎</button>
      </div>

    </div>
  )
}`
}

interface Prop {
    key: string
    value: string
    comment?: string
}

const generateProps = (props: Prop[], indent = 2): string => {
    const spaces = ' '.repeat(indent)
    return props
        .map(({ key, value, comment }) => `${spaces}${key}: ${value},${comment ? ` // ${comment}` : ''}`)
        .join('\n')
}

export function getManualCaptureExample({ surveyId = 'your-survey-id', followUpEnabled }: CodeExampleParams): string {
    const thumbsProps: Prop[] = [
        { key: '$survey_id', value: `'${surveyId}'`, comment: 'ID for the survey you just created' },
        { key: '$survey_response', value: '1', comment: '1 = thumbs up, 2 = thumbs down' },
        { key: '$ai_trace_id', value: 'traceId', comment: 'your generated trace ID' },
        ...(followUpEnabled
            ? [
                  {
                      key: '$survey_submission_id',
                      value: 'submissionId',
                      comment: 'unique ID to link thumbs + follow-up',
                  },
                  {
                      key: '$survey_completed',
                      value: 'true',
                      comment: 'or false if there is negative feedback followup',
                  },
              ]
            : []),
    ]

    const surveyShownProps: Prop[] = [
        { key: '$survey_id', value: `'${surveyId}'` },
        { key: '$ai_trace_id', value: 'traceId' },
    ]

    const submissionIdLine = followUpEnabled
        ? `// Generate a unique ID to link \`survey sent\` events into a single user feedback event
const submissionId = crypto.randomUUID()

`
        : ''

    const base = `// (Optional) Track when the survey is shown to the user
posthog.capture('survey shown', {
${generateProps(surveyShownProps)}
})

${submissionIdLine}// When user clicks thumbs up/down, send a survey event
posthog.capture('survey sent', {
${generateProps(thumbsProps)}
})`

    if (followUpEnabled) {
        const followUpProps: Prop[] = [
            { key: '$survey_id', value: `'${surveyId}'` },
            { key: '$survey_response_1', value: "'the AI hallucinated hedgehogs everywhere'" },
            { key: '$ai_trace_id', value: 'traceId' },
            {
                key: '$survey_submission_id',
                value: 'submissionId',
                comment: "must match the previous event's $survey_submission_id",
            },
            { key: '$survey_completed', value: 'true' },
        ]

        return (
            base +
            `

// If the user submitted follow-up text after thumbs down:
posthog.capture('survey sent', {
${generateProps(followUpProps)}
})`
        )
    }

    return base
}
