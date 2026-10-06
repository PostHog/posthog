import type { HogFlowAction } from '../Workflows/hogflows/types'
import type { FirstRunSender } from './firstRunSenderLogic'

export function withFirstRunSender(actions: HogFlowAction[], sender: Pick<FirstRunSender, 'id'>): HogFlowAction[] {
    return actions.map((action) =>
        action.type === 'function_email'
            ? {
                  ...action,
                  config: {
                      ...action.config,
                      inputs: {
                          ...action.config.inputs,
                          email: {
                              ...action.config.inputs.email,
                              value: {
                                  ...action.config.inputs.email?.value,
                                  from: { integrationId: sender.id },
                              },
                          },
                      },
                  },
              }
            : action
    )
}

export function firstRunSenderIdOf(actions: HogFlowAction[]): number | null {
    const firstEmail = actions.find((action) => action.type === 'function_email')
    return firstEmail?.type === 'function_email'
        ? (firstEmail.config.inputs.email?.value?.from?.integrationId ?? null)
        : null
}
