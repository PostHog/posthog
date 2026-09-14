import posthog, { DisplaySurveyType } from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

export const SCANNER_FEEDBACK_SURVEY_IDS = {
    disabled: '01a09222-52e9-0000-db25-4153580e8909',
    deleted: '01a09222-68b1-0000-51b0-6a66a308d724',
    enabled: '01a09222-811e-0000-fca9-eb93f708e5fb',
} as const

export function requestScannerFeedback(
    action: keyof typeof SCANNER_FEEDBACK_SURVEY_IDS,
    scannerId: string,
    source: 'list' | 'detail',
    teamId: number
): boolean {
    try {
        const surveyId = SCANNER_FEEDBACK_SURVEY_IDS[action]
        if (teamLogic.values.currentTeamId !== teamId || !posthog.canRenderSurvey(surveyId)?.visible) {
            return false
        }

        const distinctId = posthog.get_distinct_id()
        const display = (): void => {
            try {
                if (teamLogic.values.currentTeamId !== teamId || posthog.get_distinct_id() !== distinctId) {
                    return
                }
                posthog.displaySurvey(surveyId, {
                    displayType: DisplaySurveyType.Popover,
                    ignoreConditions: false,
                    ignoreDelay: true,
                    properties: {
                        scanner_id: scannerId,
                        scanner_action: action,
                        scanner_feedback_source: source,
                        project_id: teamId,
                    },
                })
            } catch {
                return
            }
        }

        if (action === 'enabled') {
            const storageKey = `replay-vision-enable-feedback-offered:${distinctId}`
            if (sessionStorage.getItem(storageKey)) {
                return false
            }
            sessionStorage.setItem(storageKey, 'true')
            lemonToast.success('Scanner enabled', {
                toastId: 'replay-vision-enable-feedback',
                button: {
                    label: 'Share your goal',
                    action: display,
                    dataAttr: 'replay-vision-enable-feedback',
                },
            })
        } else {
            display()
        }
        return true
    } catch {
        return false
    }
}
