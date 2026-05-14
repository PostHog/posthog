import { useEffect, useRef, useState } from 'react'

/** Phrase cycle interval. Long enough to read, short enough to feel alive. */
const ROTATE_MS = 3500

/**
 * 100 cycle-under-the-spinner phrases for the landing-page generator's loading states.
 *
 * Voice: PostHog-style — direct, founder-empathy, mild ribbing, occasional hedgehog. Not
 * "your AI assistant" energy. Most lines work both as a literal status update and a wink
 * at the absurdity of building landing pages in 2026.
 *
 * Keep each line under ~80 chars so it fits on one row in the preview card.
 */
export const SPINNER_PHRASES: readonly string[] = [
    'Asking Gemini to please write something good this time',
    "Convincing the LLM your idea isn't another todo app",
    'Picking colors that aren’t blue (also picking blue)',
    'Removing the words “leverage” and “synergy”',
    'Drafting "trusted by leading companies" without any companies',
    'Asking ourselves: do we really need a pricing page?',
    'Talking ourselves out of a hero animation',
    'Building the page Steve Jobs would have shipped (probably)',
    'Wondering if we should rip off Linear’s design again',
    'Replacing "users" with "you" — it’s friendlier',
    'Calculating how many founders Cursor has put out of work',
    'Removing the parts where the LLM hallucinated',
    'Asking Max the hedgehog for feedback',
    'Max said: ship it',
    'Generating testimonials from imaginary customers',
    'Adding subtle gradients founders love',
    'Removing the subtle gradients (too 2024)',
    'Drafting a tagline that doesn’t include "AI-powered"',
    'Failing to draft a tagline that doesn’t include "AI-powered"',
    'Asking Stripe how they make their landing page look so good',
    'Writing "Get started free" in 47 places',
    'Convincing the model to be more concrete and less salesy',
    'Picking between "the future of X" and "X, reimagined"',
    'Trying to look like a Series B on a hackathon budget',
    'Building a page nobody asked for',
    'Adding "no credit card required" (this is true)',
    'Making the CTA button bigger',
    'Making the CTA button smaller (it was too big)',
    'Centering a div (still hard in 2026)',
    'Removing all the em dashes — wait',
    'Reading Linear’s design system docs for the 38th time',
    'Writing copy that doesn’t sound like ChatGPT',
    'Renaming "Sign up" to "Start free" to "Get started"',
    'Removing the "Trusted by" section (it was a lie)',
    'Picking a shade of green that says "growth"',
    'Hiding the actual price',
    'Showing the actual price',
    'Adding social proof from imaginary friends',
    'Optimizing for Lighthouse scores nobody will check',
    'Generating SVG icons that don’t all look like checkmarks',
    'Picking a font that says "we have taste"',
    'Asking ourselves: would a hedgehog buy this?',
    'Probably yes. They have low standards.',
    'Writing micro-copy for the empty state',
    'Building the page Cal.com built in 2022',
    'Negotiating with our inner perfectionist',
    'Removing 30% of the copy (it was redundant)',
    'Adding back 20% of the copy (it was important)',
    'Calling the model again because the first answer was mid',
    'Writing FAQs that secretly answer "are you a real company?"',
    'Picking words shorter than four syllables',
    'Trying to be more Stripe, less generic SaaS',
    'Asking: what would DHH do?',
    'Writing a hero subhead under 12 words',
    'Failing to write a hero subhead under 12 words',
    'Centering the logo (it’s off by 1px and you can tell)',
    'Picking colors that work on light AND dark backgrounds',
    'Writing for the 3am insomnia founder, not the LinkedIn flex one',
    'Asking Gemini to please not say "in today’s fast-paced world"',
    'Replacing "platform" with literally anything else',
    'Removing "industry-leading" before legal sees it',
    'Generating pricing tiers nobody picks (it’s always the middle one)',
    'Filing off the corners on every card (subtle border radius)',
    'Optimizing for the LinkedIn share preview card',
    'Asking the model to be 30% more concrete',
    'The model added bullet points instead. Close enough.',
    'Picking icons that aren’t all from Heroicons (we picked Heroicons)',
    'Generating a logo that’s two letters in a colored square',
    'Stress-testing the copy against "would my dad get this"',
    'Removing all the em dashes (the LLM uses way too many)',
    '(Adding them back. They’re useful.)',
    'Picking between Inter and Geist (you know it’s Inter)',
    'Building the landing page Vercel would build',
    'Writing pricing that doesn’t hide behind "Contact us"',
    'Generating screenshots that look like a real product',
    'Asking ourselves: should this be a Notion page instead?',
    'Writing the page Paul Graham would skim and not hate',
    'Drafting CTAs that beat "Learn more"',
    'Convincing the model "Learn more" is the worst CTA ever',
    'Filtering out "seamless" and "intuitive"',
    'Picking microcopy for the email-capture input',
    'Writing "no spam, ever" and meaning it',
    'Removing the dark mode toggle (one fewer thing to break)',
    'Wondering if a sticky CTA bar is too tacky',
    'Yes. Always yes.',
    'Asking if we really need a video on the hero',
    'Cutting the video. We don’t have one anyway.',
    'Writing pricing tiers that don’t say "Contact us"',
    'Generating 12 placeholder names that aren’t all "Acme"',
    'Asking if a launch tweet has to be cringe',
    'Researching: spoiler, yes',
    'Picking emojis the founder won’t regret in two years',
    'Removing all the emojis (we regret them)',
    'Writing a 404 page we’ll never see',
    'Asking: would a YC partner read past the fold?',
    'Probably not. Shipping it anyway.',
    'Generating proof points without the proof',
    'Writing testimonials from customers we don’t have yet',
    'Adding "We use PostHog" (you should too)',
    'Picking a vibe between "Notion for X" and "Linear for X"',
    'Refactoring the hero for the third time today',
    'Reminding the LLM that less is more',
    'Reminding the LLM again',
    'Shipping the page Steve Jobs would have shipped (90% probably)',
]

/** Cycle through a fresh shuffle of phrases every `ROTATE_MS` ms. */
export function useShuffledPhrase(intervalMs: number = ROTATE_MS): string {
    const order = useRef<readonly string[]>(SPINNER_PHRASES)
    const [idx, setIdx] = useState(0)

    useEffect(() => {
        // Fisher-Yates shuffle a fresh copy on mount so each load feels different. We
        // hold the shuffle in a ref so the interval reads the same order even if the
        // component re-renders for an unrelated reason.
        const arr = [...SPINNER_PHRASES]
        for (let i = arr.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1))
            ;[arr[i], arr[j]] = [arr[j], arr[i]]
        }
        order.current = arr
        setIdx(0)
        const id = window.setInterval(() => setIdx((i) => (i + 1) % arr.length), intervalMs)
        return () => window.clearInterval(id)
    }, [intervalMs])

    return order.current[idx] ?? ''
}
