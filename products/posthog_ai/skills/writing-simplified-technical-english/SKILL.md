---
name: writing-simplified-technical-english
description: 'Write English that a reader cannot misread: one meaning per word, active voice, simple tenses, one idea per sentence, short sentences. Based on ASD-STE100 (Simplified Technical English), the controlled-language standard written for aircraft maintenance manuals. Use it for any prose an agent produces that someone else acts on. That covers reports and findings, PR descriptions and commit messages, instructions handed to another agent, tool descriptions, error messages, status summaries, and prompts. Also use it on request, with triggers like "simplify this", "make this readable", "too dense", "rewrite in STE", "simplified technical english", "ASD-STE100".'
---

# Writing simplified technical English

ASD-STE100 is a controlled-language standard.
The aerospace and defense industry wrote it so that a technician cannot misread a maintenance instruction.
It removes the two biggest sources of misreading: words that carry more than one meaning, and sentences that support more than one structure.

The same discipline fixes the usual failure of agent-written prose.
Agent output is often correct and unreadable: long sentences, stacked hedges, passive voice, and a synonym rotation that makes one action look like three.
The reader has no author to ask, so ambiguity costs them a re-read at best and a wrong action at worst.

Apply the rules below as you write.
Do not write a dense draft and clean it up afterward.

## When to use this

Use it for text that a person or another agent must act on:

- Reports, findings, and summaries.
- PR descriptions, commit messages, and code comments.
- Instructions passed to another agent, and prompts.
- Tool descriptions, error messages, empty states, and log lines.

Do not use it where voice is the point: marketing copy, blog posts, or anything persuasive.
STE is deliberately flat.
Also leave quoted text alone.
If you quote a user, a log, or a document, quote it as it is.

## The rules

| Rule                        | Do                                                                   | Do not                                                      |
| --------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------- |
| One meaning per word        | Pick one verb per action and reuse it every time                     | Rotate "check", "verify", and "confirm" for the same action |
| One part of speech per word | "Apply oil to the valve"                                             | "Oil the valve"                                             |
| Active voice                | "The worker deletes the file."                                       | "The file is deleted."                                      |
| Simple tenses               | "We received the report."                                            | "We have received the report."                              |
| One idea per sentence       | "Open the file. Read line 3."                                        | "Open the file and read line 3, then check it matches."     |
| Sentence length             | 20 words or fewer for instructions, 25 or fewer for descriptions     | Chains of subordinate clauses                               |
| Noun clusters               | 3 words or fewer ("fuel pump valve")                                 | "high pressure fuel pump inlet valve assembly"              |
| No missing words            | Keep the subject, the verb, and the article, even if it reads longer | "Files not backed up will be lost", which hides which files |
| One hedge, at most          | "The client version is probably out of date."                        | "An error may have occurred which could be caused by..."    |
| Paragraphs                  | One topic, 6 sentences or fewer                                      | Multi-topic paragraphs                                      |
| Lists                       | Use a list for 3 or more steps or conditions                         | A sequence buried in one sentence                           |
| Jargon                      | Keep the technical term you need, and define it once                 | Use an internal name the reader has never seen              |

PostHog house style sits on top of these rules and wins where the two disagree.
We use American English, sentence case, and the Oxford comma.
We do not use the em-dash.

## How to rewrite

1. Read the text once for meaning. Do not start rewriting before you know what it must still say.
2. Go sentence by sentence. Name the rule each sentence breaks.
3. Rewrite the sentence to fix that break. Keep every fact, number, condition, and qualifier.
4. Check the result against the rules again. A rewrite often introduces a new long sentence.

Precision beats brevity.
If a shorter sentence would drop a safety condition, a scope qualifier, or a number, keep the longer sentence and say why.

If the text already follows the rules, say so.
Do not change compliant text.

## Self-check

Before you send the text, read it once and ask:

- Does any sentence run past 25 words?
- Does any sentence carry two instructions?
- Does the same action appear under two different verbs?
- Can a passive sentence name its actor?
- Would a reader who joins here, with no context, know what to do next?

## References

- `references/writing-rules.md`: the detail behind the table, plus sources.
- `references/before-after.md`: worked examples of the rewrite, including agent output.
