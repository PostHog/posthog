import { useActions, useValues } from 'kea'
import { useState } from 'react'

import api from 'lib/api'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { founderLogic } from '../scenes/founderLogic'

// Mock stage 1 to unblock the validation demo. Real implementation will be a richer form +
// kea logic; for now we just need to create a FounderProject row and stash its id so Step2
// can read it.

const SAMPLE_IDEA = {
    name: 'HOA Cofounder',
    what: 'An AI-powered tool that helps homeowners associations manage meetings, votes, and budgets.',
    how: 'Web app that ingests meeting recordings and bylaws, produces summaries, drafts agendas, and tracks votes.',
    who: 'HOA board members at 5-200 unit complexes, mostly volunteers who manage the HOA part-time.',
    problem:
        'HOA boards burn out from manual minute-taking, chasing votes, and reconciling bylaws. Existing software is clunky and built for property managers, not volunteer boards.',
}

export function Step1(): JSX.Element {
    const { currentProjectId } = useValues(founderLogic)
    const { setCurrentProjectId, setStep } = useActions(founderLogic)
    const [name, setName] = useState(SAMPLE_IDEA.name)
    const [what, setWhat] = useState(SAMPLE_IDEA.what)
    const [how, setHow] = useState(SAMPLE_IDEA.how)
    const [who, setWho] = useState(SAMPLE_IDEA.who)
    const [problem, setProblem] = useState(SAMPLE_IDEA.problem)
    const [submitting, setSubmitting] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const onSubmit = async (): Promise<void> => {
        setSubmitting(true)
        setError(null)
        try {
            const project = await api.create<{ id: string }>('api/projects/@current/founder_projects/', {
                name,
                ideation: { what, how, who, problem },
            })
            setCurrentProjectId(project.id)
            setStep(2)
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <header>
                <h2 className="text-xl font-semibold">Ideation</h2>
                <p className="text-sm text-text-secondary mt-1">
                    Describe your startup idea. The validation step uses this as context for competitor research and
                    assumption-testing.
                </p>
            </header>

            {currentProjectId && (
                <LemonBanner type="success">
                    A project is already in progress. Click "Save & continue" to overwrite, or skip to the next stage.
                </LemonBanner>
            )}

            <Field label="Project name">
                <LemonTextArea value={name} onChange={setName} minRows={1} maxRows={1} />
            </Field>
            <Field label="What are you building?">
                <LemonTextArea value={what} onChange={setWhat} minRows={2} />
            </Field>
            <Field label="How does it work?">
                <LemonTextArea value={how} onChange={setHow} minRows={2} />
            </Field>
            <Field label="Who is it for?">
                <LemonTextArea value={who} onChange={setWho} minRows={2} />
            </Field>
            <Field label="What problem does it solve?">
                <LemonTextArea value={problem} onChange={setProblem} minRows={2} />
            </Field>

            {error && <LemonBanner type="error">Failed to create project: {error}</LemonBanner>}

            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    onClick={onSubmit}
                    loading={submitting}
                    disabledReason={!what || !who ? 'Fill in what + who first' : undefined}
                >
                    Save & continue
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => setStep(2)}
                    disabledReason={!currentProjectId ? 'Save the project first' : undefined}
                >
                    Skip to validation
                </LemonButton>
            </div>
        </div>
    )
}

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">{label}</span>
            {children}
        </label>
    )
}
