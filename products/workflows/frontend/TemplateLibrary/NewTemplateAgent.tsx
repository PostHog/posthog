import { useActions, useValues } from 'kea'

import { IconLetter } from '@posthog/icons'

import { AiFirstCreateScene } from 'scenes/max/aiFirstCreate/AiFirstCreateScene'
import { aiFirstHandoffLogic } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'

import { messageTemplatesLogic } from './messageTemplatesLogic'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { NEW_TEMPLATE_HANDOFF } from './newTemplateHandoff'
import { NEW_TEMPLATE_SUGGESTIONS, PICKED_TEMPLATE_PROMPT } from './templateAgentContext'
import { TemplateStartingPointCard } from './TemplateStartingPointCard'
import { MessageTemplate } from './types'

// The library lists every saved template; the row shows the newest few so the prompt cards stay in view.
const STARTING_POINT_LIMIT = 8

/** The AI-first "New template" screen: the composer first, with the team's saved templates as starting points. */
export function NewTemplateAgent(): JSX.Element {
    const { openEditorFromAiComposer, setPickedTemplate } = useActions(newTemplateAgentLogic)
    const { pickedTemplate } = useValues(newTemplateAgentLogic)
    const { fillComposer } = useActions(aiFirstHandoffLogic(NEW_TEMPLATE_HANDOFF))
    const { templates, templatesLoading } = useValues(messageTemplatesLogic)

    const pickTemplate = (template: MessageTemplate): void => {
        setPickedTemplate(template)
        fillComposer(PICKED_TEMPLATE_PROMPT)
    }
    const startingPoints = templates.slice(0, STARTING_POINT_LIMIT)

    return (
        <AiFirstCreateScene
            handoff={NEW_TEMPLATE_HANDOFF}
            banner="We're trialling designing email templates with PostHog AI. Describe the email you want and it drafts the template for you to refine."
            escapeHatchLabel="Use the editor instead"
            onEscapeHatch={openEditorFromAiComposer}
            suggestions={NEW_TEMPLATE_SUGGESTIONS}
            suggestionIcon={<IconLetter />}
            belowComposer={
                // Nothing to pick from is not an empty state worth a screen; the prompt cards are the page then.
                !templatesLoading && startingPoints.length > 0 ? (
                    // Same width as the composer, with no side padding, so four cards fit in one row and the
                    // edges line up. The bottom margin keeps the pick row apart from the prompt cards.
                    <div
                        className="flex flex-col gap-2 w-full max-w-2xl mb-4"
                        data-attr="new-template-agent-starting-points"
                    >
                        <span className="text-secondary text-xs font-semibold">Start from a template</span>
                        <div className="flex flex-wrap gap-2">
                            {startingPoints.map((template) => (
                                <TemplateStartingPointCard
                                    key={template.id}
                                    template={template}
                                    picked={pickedTemplate?.id === template.id}
                                    onClick={() => pickTemplate(template)}
                                />
                            ))}
                        </div>
                    </div>
                ) : null
            }
            dataAttr="new-template-agent"
        />
    )
}
