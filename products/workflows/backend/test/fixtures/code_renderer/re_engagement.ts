// @posthog/workflows cannot express everything in this workflow. Review these before you push:
// - wait_for_a_click: The branch edges out of "Wait for a click" are dropped. Only its next step is kept.
// - wait_for_a_click: The wait_until_condition step "Wait for a click" has no constructor in @posthog/workflows. It is kept in place as a comment.
// - text_them: The function_sms step "Text them" has no constructor in @posthog/workflows. It is kept in place as a comment.
// - nudge_by_email: The email design of "Nudge by email" was edited in the visual editor. @posthog/workflows rebuilds the design from html, so that layout is dropped.

import { email, onEvent, path, workflow } from '@posthog/workflows'

export const reEngagement = workflow({
    key: 're-engagement',
    name: 'Re-engagement',
    status: 'active',
    on: onEvent({ event: 'trial started' }),
    steps: path(
        // The wait_until_condition step "Wait for a click" is kept as JSON. Replace it or remove it before you push.
        // {
        //     "id": "wait_for_a_click",
        //     "name": "Wait for a click",
        //     "description": "",
        //     "on_error": null,
        //     "filters": null,
        //     "type": "wait_until_condition",
        //     "config": {
        //         "condition": {
        //             "filters": {
        //                 "events": [
        //                     {
        //                         "id": "$autocapture",
        //                         "name": "$autocapture",
        //                         "type": "events",
        //                         "order": 0
        //                     }
        //                 ]
        //             }
        //         },
        //         "max_wait_duration": "3d"
        //     }
        // }
        // The function_sms step "Text them" is kept as JSON. Replace it or remove it before you push.
        // {
        //     "id": "text_them",
        //     "name": "Text them",
        //     "description": "",
        //     "on_error": null,
        //     "filters": null,
        //     "type": "function_sms",
        //     "config": {
        //         "template_id": "template-twilio",
        //         "inputs": {
        //             "to": {
        //                 "value": "{person.properties.phone}",
        //                 "order": 0
        //             },
        //             "body": {
        //                 "value": "Your trial ends soon. Come back and finish setup.",
        //                 "order": 1
        //             }
        //         },
        //         "message_category_type": "marketing"
        //     }
        // }
        email({
            name: 'Nudge by email',
            from: { integrationIds: [7] },
            to: '{person.properties.email}',
            subject: 'Your trial ends soon',
            text: 'Come back and finish setup.',
            html: '<p>Come back and finish setup.</p>',
        }),
    ),
    exit: { reason: 'Done' },
})
