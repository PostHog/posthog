import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'

export function CodeManagedNotice(props: MessageTemplateLogicProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { isDuplicating, changeRun } = useValues(logic)
    const { duplicateTemplate } = useActions(logic)

    return (
        <LemonBanner
            type="info"
            className="shrink-0"
            action={{
                children: 'Duplicate',
                onClick: duplicateTemplate,
                loading: isDuplicating,
                'data-attr': 'message-template-code-managed-duplicate',
            }}
        >
            <p className="m-0">
                This template is managed by code, so it can't be changed here. To change it, edit its file, or let your
                coding agent do it.
            </p>
            {changeRun && (
                <p className="m-0 mt-1" data-attr="message-template-change-run-notice">
                    PostHog Code is working on it. It opens a pull request when it's done.{' '}
                    <Link to={urls.taskDetail(changeRun.task_id)} data-attr="message-template-change-run-task">
                        Open task
                    </Link>
                </p>
            )}
        </LemonBanner>
    )
}
