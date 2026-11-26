import type { Editor } from '@tiptap/core'

import { LemonButton, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { setBlockAttribute } from '../emailCommands'
import { EmailCondition, EmailVisibility } from '../emailDocument'
import { safeEmailVisibility } from '../renderEmailHtml'
import { EmailFieldRow } from './fields/EmailFieldRow'
import { EmailSectionTitle } from './fields/EmailSectionTitle'

type Screens = 'all' | 'desktop' | 'mobile'

// One space each side belongs to the tag. Any other is being typed.
const SIMPLE_CONDITION = /^\{%-?\s*if\s([\s\S]*?)\s?-?%\}$/
const END_IF = /^\{%-?\s*endif\s*-?%\}$/

/** The expression of a plain `{% if … %}…{% endif %}`, or null when the condition is written some other way. */
function simpleExpression(condition: EmailCondition): string | null {
    const match = SIMPLE_CONDITION.exec(condition.before.trim())
    return match && END_IF.test(condition.after.trim()) ? match[1] : null
}

function screensOf(visibility: EmailVisibility | null): Screens {
    return visibility?.hideMobile && !visibility.hideDesktop
        ? 'desktop'
        : visibility?.hideDesktop && !visibility.hideMobile
          ? 'mobile'
          : 'all'
}

export function EmailVisibilityFields({ editor, pos }: { editor: Editor; pos: number }): JSX.Element | null {
    const node = editor.state.doc.nodeAt(pos)
    if (!node || !('emailVisibility' in node.attrs)) {
        return null
    }
    const visibility = safeEmailVisibility(node.attrs.emailVisibility)
    const condition = visibility?.condition
    const expression = condition ? simpleExpression(condition) : null
    const update = (patch: Partial<EmailVisibility>): void => {
        const next = safeEmailVisibility({ ...visibility, ...patch })
        setBlockAttribute(editor, pos, 'emailVisibility', next)
    }
    const setCondition = (next: EmailCondition | undefined): void => update({ condition: next })

    return (
        <>
            <EmailSectionTitle>Who sees it</EmailSectionTitle>
            <EmailFieldRow label="Screens" group>
                <LemonSegmentedButton
                    size="xsmall"
                    fullWidth
                    value={screensOf(visibility)}
                    onChange={(screens: Screens) =>
                        update({ hideDesktop: screens === 'mobile', hideMobile: screens === 'desktop' })
                    }
                    options={[
                        { value: 'all', label: 'All', 'data-attr': 'email-editor-visibility-screens-all' },
                        { value: 'desktop', label: 'Desktop', 'data-attr': 'email-editor-visibility-screens-desktop' },
                        { value: 'mobile', label: 'Phones', 'data-attr': 'email-editor-visibility-screens-mobile' },
                    ]}
                />
            </EmailFieldRow>
            {!condition ? (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    fullWidth
                    center
                    onClick={() => setCondition({ before: '{% if  %}', after: '{% endif %}' })}
                    data-attr="email-editor-visibility-add-condition"
                >
                    Show only when…
                </LemonButton>
            ) : expression !== null ? (
                <EmailFieldRow label="Only if">
                    <LemonInput
                        size="small"
                        fullWidth
                        placeholder="person.properties.plan == 'paid'"
                        value={expression}
                        onChange={(value) =>
                            setCondition({ ...condition, before: `{% if ${value} %}`, after: '{% endif %}' })
                        }
                        data-attr="email-editor-visibility-condition"
                    />
                </EmailFieldRow>
            ) : (
                <>
                    <EmailFieldRow label="Before">
                        <LemonInput
                            size="small"
                            fullWidth
                            value={condition.before}
                            onChange={(before) => setCondition({ ...condition, before })}
                            data-attr="email-editor-visibility-before"
                        />
                    </EmailFieldRow>
                    <EmailFieldRow label="After">
                        <LemonInput
                            size="small"
                            fullWidth
                            value={condition.after}
                            onChange={(after) => setCondition({ ...condition, after })}
                            data-attr="email-editor-visibility-after"
                        />
                    </EmailFieldRow>
                </>
            )}
            {condition ? (
                <>
                    <EmailFieldRow label="Name">
                        <LemonInput
                            size="small"
                            fullWidth
                            placeholder="Paying customers"
                            value={condition.label ?? ''}
                            onChange={(label) => setCondition({ ...condition, label: label || undefined })}
                            data-attr="email-editor-visibility-label"
                        />
                    </EmailFieldRow>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        status="danger"
                        onClick={() => setCondition(undefined)}
                        data-attr="email-editor-visibility-remove-condition"
                    >
                        Show to everyone
                    </LemonButton>
                </>
            ) : null}
        </>
    )
}
