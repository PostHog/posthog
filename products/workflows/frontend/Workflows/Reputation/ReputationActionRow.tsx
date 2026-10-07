import clsx from 'clsx'
import { useActions } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import type { ReputationAction } from './actions/reputationActionTypes'
import { reputationActionListLogic } from './reputationActionListLogic'
import { actionStyle } from './reputationUtils'

export function ReputationActionRow({ action, position }: { action: ReputationAction; position: number }): JSX.Element {
    const { runActionCta } = useActions(reputationActionListLogic)
    const style = actionStyle(action)
    // pinned: autocapture data-attr, so renaming it breaks click insights built on it
    const dataAttr = `workflows-reputation-action-${action.kind}`
    const { cta, docsLink } = action
    return (
        <li
            className={clsx(
                'flex flex-col gap-3 px-4 py-3 border-b border-l-2 last:border-b-0 @xl:flex-row @xl:items-center',
                style.border
            )}
            data-attr="workflows-reputation-action"
        >
            <div className="flex gap-3 flex-1 min-w-0">
                <span className="text-secondary tabular-nums w-5 shrink-0" aria-hidden>
                    {position}
                </span>
                <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="font-semibold break-words">{action.title}</span>
                        <LemonTag type={style.tagType} size="small">
                            {style.label}
                        </LemonTag>
                    </div>
                    <p className="text-secondary mb-0 mt-1">
                        {action.description}
                        {docsLink && (
                            <>
                                {' '}
                                <Link to={docsLink.to} target="_blank" data-attr={`${dataAttr}-docs`}>
                                    {docsLink.label}
                                </Link>
                            </>
                        )}
                    </p>
                </div>
            </div>
            {cta && (
                <div className="flex justify-end shrink-0">
                    {/* One width for every row's button, so the buttons line up in a column down the list. */}
                    <LemonButton
                        type="secondary"
                        size="small"
                        center
                        className="w-36"
                        to={cta.to}
                        onClick={cta.onClick ? () => runActionCta(action.key) : undefined}
                        data-attr={dataAttr}
                    >
                        {cta.label}
                    </LemonButton>
                </div>
            )}
        </li>
    )
}
