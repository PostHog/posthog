import { KeyboardEvent } from 'react'

export function navigateSurveyChoices(event: KeyboardEvent<HTMLDivElement>): void {
    if (
        event.defaultPrevented ||
        event.nativeEvent.isComposing ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        event.shiftKey ||
        !(event.target instanceof HTMLInputElement) ||
        event.target.type !== 'checkbox'
    ) {
        return
    }
    const direction = ['ArrowDown', 'ArrowRight'].includes(event.key)
        ? 1
        : ['ArrowUp', 'ArrowLeft'].includes(event.key)
          ? -1
          : 0
    if (!direction) {
        return
    }
    const options = Array.from(event.currentTarget.querySelectorAll<HTMLInputElement>('input[type="checkbox"]:enabled'))
    const index = options.indexOf(event.target)
    if (index === -1) {
        return
    }
    event.preventDefault()
    event.stopPropagation()
    options[(index + direction + options.length) % options.length].focus()
}

export function advanceSurveyFocus(event: KeyboardEvent<HTMLDivElement>): void {
    if (
        event.defaultPrevented ||
        event.nativeEvent.isComposing ||
        event.key !== 'Enter' ||
        event.altKey ||
        event.shiftKey
    ) {
        return
    }
    if (!(event.target instanceof HTMLElement) || !event.currentTarget.contains(event.target)) {
        return
    }
    if (event.repeat) {
        event.preventDefault()
        event.stopPropagation()
        return
    }
    const target = event.target
    const isTextAnswer = target instanceof HTMLTextAreaElement
    const isChoice = target instanceof HTMLInputElement && ['radio', 'checkbox'].includes(target.type)
    if ((!isTextAnswer && !isChoice) || isTextAnswer !== (event.metaKey || event.ctrlKey)) {
        return
    }
    event.preventDefault()
    event.stopPropagation()
    const questions = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[data-survey-question]'))
    const current = target.closest<HTMLElement>('[data-survey-question]')
    const index = current ? questions.indexOf(current) : -1
    if (index === -1) {
        return
    }
    const next = questions
        .slice(index + 1)
        .find((question) => question.querySelector('input:enabled, textarea:enabled'))
    const control = next
        ? next.querySelector<HTMLElement>('input:enabled:checked') ||
          next.querySelector<HTMLElement>('input:enabled, textarea:enabled')
        : event.currentTarget.querySelector<HTMLElement>('[data-attr="api-survey-submit"]:not(:disabled)')
    control?.focus()
}
