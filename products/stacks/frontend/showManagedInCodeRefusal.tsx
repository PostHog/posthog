import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanList } from 'lib/utils/strings'

import type { DefinitionSourceRefApi } from './generated/api.schemas'
import { definitionFileUrl, fieldLabel, kindLabel } from './managedInCode'
import { openAskForChangeDialog } from './openAskForChangeDialog'

/**
 * The `extra` of a 409 with code `managed_in_code`. The generated `StackErrorResponseApiExtra` is an untyped map, so this
 * names the keys the API documents for this code.
 */
export interface ManagedInCodeRefusal {
    stack?: string
    repository?: string
    source?: DefinitionSourceRefApi | null
    fields?: string[]
    kind?: string
    binding_id?: string
}

/** Tells the person which file to edit after the API refused a write to a field that code owns. */
export function showManagedInCodeRefusal(refusal: ManagedInCodeRefusal, detail?: string): void {
    const kind = refusal.kind ?? ''
    const file = refusal.source?.file
    const fields = refusal.fields ?? []
    const label = kind ? `this ${kindLabel(kind)}` : 'this'
    const fieldText = fields.length ? humanList(fields.map((path) => fieldLabel(kind, path))) : null
    const fileUrl = definitionFileUrl(refusal.repository ?? '', refusal.source ?? null)
    const canAsk =
        !!featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.POSTHOG_AS_CODE] &&
        !!refusal.binding_id &&
        !!refusal.stack

    // pinned: analytics event name and properties, renaming breaks dashboards
    posthog.capture('managed in code refusal shown', {
        kind: kind || null,
        field_count: fields.length,
        has_source_file: !!file,
        can_ask_for_change: canAsk,
    })

    const message =
        file || refusal.stack ? (
            <span>
                {fieldText ? `Couldn't save the ${fieldText} of ${label}` : `Couldn't save ${label}`}, because it is
                managed in code
                {refusal.stack ? (
                    <>
                        {' '}
                        by the stack <code>{refusal.stack}</code>
                    </>
                ) : null}
                .{' '}
                {file ? (
                    <>
                        Edit <code>{file}</code>
                        {refusal.repository ? (
                            <>
                                {' '}
                                in <code>{refusal.repository}</code>
                            </>
                        ) : null}{' '}
                        instead.
                    </>
                ) : (
                    'Change its definition in the repository instead.'
                )}
            </span>
        ) : (
            (detail ?? `Couldn't save ${label}, because it is managed in code.`)
        )

    lemonToast.error(message, {
        toastId: 'managed-in-code-refusal',
        button: canAsk
            ? {
                  label: 'Ask for a change',
                  dataAttr: 'managed-in-code-refusal-ask-for-change',
                  action: () =>
                      openAskForChangeDialog({
                          binding: {
                              id: refusal.binding_id!,
                              stack_name: refusal.stack!,
                              repository: refusal.repository ?? '',
                              source: refusal.source ?? null,
                              kind,
                          },
                          refusedFields: fields,
                          entryPoint: 'refusal',
                      }),
              }
            : fileUrl
              ? {
                    label: 'Open file',
                    dataAttr: 'managed-in-code-refusal-open-file',
                    action: () => window.open(fileUrl, '_blank', 'noopener'),
                }
              : undefined,
    })
}
