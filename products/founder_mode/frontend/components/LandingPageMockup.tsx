import { useMemo } from 'react'

import { IconExternal, IconGithub } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { LandingPageBuildSpec } from './founderLandingPageLogic'
import { useShuffledPhrase } from './spinnerPhrases'

interface Props {
    /** Local mock spec for the inline preview. Used when `liveUrl` isn't ready yet. */
    spec?: LandingPageBuildSpec
    /** Live URL to iframe in the preview body. When set, replaces the local mock entirely. */
    liveUrl?: string | null
    /** When true, suppress the local mock and show a loading body. */
    loading?: boolean
    /** Loading copy shown under the spinner. */
    loadingLabel?: string
    /** Footer copy. Defaults to a "mockup vs final" disclaimer. */
    footerLabel?: string
    /** GitHub repo URL — when present, BrowserChrome shows a "View on GitHub" icon button. */
    repoUrl?: string | null
}

export function LandingPageMockup({ spec, liveUrl, loading, loadingLabel, footerLabel, repoUrl }: Props): JSX.Element {
    // URL bar contents: prefer the live URL, otherwise show a fake `.com` derived from the spec.
    const url = useMemo(() => {
        if (liveUrl) {
            return liveUrl
        }
        if (spec) {
            return `https://${slugify(spec.project_name)}.com`
        }
        return 'about:blank'
    }, [liveUrl, spec])

    const handleOpenInTab = (): void => {
        if (liveUrl) {
            window.open(liveUrl, '_blank', 'noopener')
            return
        }
        if (!spec) {
            return
        }
        const html = renderLandingPageHtml(spec)
        const blob = new Blob([html], { type: 'text/html' })
        const objectUrl = URL.createObjectURL(blob)
        window.open(objectUrl, '_blank', 'noopener')
        // Object URL is freed by the browser when the spawned tab closes — revoking it
        // here would break the navigation before the page loads.
    }

    const canOpen = !!liveUrl || !!spec
    const renderMode: 'live' | 'loading' | 'mock' | 'empty' = liveUrl ? 'live' : loading || !spec ? 'loading' : 'mock'

    return (
        <LemonCard className="p-0 overflow-hidden">
            <BrowserChrome url={url} onOpen={canOpen ? handleOpenInTab : null} repoUrl={repoUrl} />
            <div className="relative bg-white min-h-[480px]">
                {renderMode === 'live' && (
                    <iframe src={liveUrl ?? ''} title="Live landing page" className="w-full h-[640px] border-0" />
                )}
                {renderMode === 'loading' && <LoadingBody label={loadingLabel} />}
                {renderMode === 'mock' && spec && <PreviewBody spec={spec} />}
                <div className="pointer-events-none absolute inset-0 ring-1 ring-inset ring-black/5" />
            </div>
            <p className="px-4 py-2 text-[11px] text-text-tertiary border-t border-border bg-bg-3000">
                {footerLabel ??
                    (renderMode === 'live'
                        ? 'Live preview — your page is published.'
                        : 'Mockup preview — not the final page. Use the build spec below to ship the real thing.')}
            </p>
        </LemonCard>
    )
}

function LoadingBody({ label }: { label?: string }): JSX.Element {
    // Cycle a fresh shuffle of ~100 PostHog-style phrases under the spinner so the
    // founder isn't watching a static "loading…" screen for two minutes. The optional
    // `label` (phase name like "Publishing to GitHub Pages") sits subtly above the
    // phrase as real context — the phrase is purely entertainment.
    const phrase = useShuffledPhrase()
    return (
        <div className="flex flex-col items-center justify-center gap-3 px-6 py-24 text-center min-h-[480px]">
            <Spinner className="text-primary" />
            {label && <p className="text-[11px] uppercase tracking-widest text-text-tertiary">{label}</p>}
            <p key={phrase} className="text-sm text-text-secondary max-w-md transition-opacity">
                {phrase}
            </p>
        </div>
    )
}

function BrowserChrome({
    url,
    onOpen,
    repoUrl,
}: {
    url: string
    onOpen: (() => void) | null
    repoUrl?: string | null
}): JSX.Element {
    // URL bar: callers may already pass a full https:// URL (live mode) or just a host
    // (mock mode). Don't double-prefix.
    const displayUrl = url.startsWith('http') ? url : `https://${url}`
    return (
        <div className="flex items-center gap-3 px-3 py-2 border-b border-border bg-bg-3000">
            <div className="flex items-center gap-1.5 shrink-0">
                <span className="w-2.5 h-2.5 rounded-full bg-red-400" />
                <span className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
                <span className="w-2.5 h-2.5 rounded-full bg-green-400" />
            </div>
            <div className="flex-1 min-w-0">
                <div className="px-3 py-1 rounded-full bg-white border border-border text-xs text-text-secondary truncate text-center">
                    {displayUrl}
                </div>
            </div>
            {repoUrl && (
                <Link
                    to={repoUrl}
                    target="_blank"
                    targetBlankIcon={false}
                    className="text-xs px-2 py-1 rounded border border-border hover:bg-fill-highlight-100 cursor-pointer flex items-center gap-1 shrink-0 text-text-primary no-underline"
                    title="View source on GitHub"
                >
                    <IconGithub className="w-3.5 h-3.5" />
                    <span className="hidden md:inline">GitHub</span>
                </Link>
            )}
            {onOpen && (
                <button
                    type="button"
                    onClick={onOpen}
                    className="text-xs px-2 py-1 rounded border border-border hover:bg-fill-highlight-100 cursor-pointer flex items-center gap-1 shrink-0"
                    title="Open in new tab"
                >
                    <IconExternal className="w-3.5 h-3.5" />
                    Open in new tab
                </button>
            )}
        </div>
    )
}

function PreviewBody({ spec }: { spec: LandingPageBuildSpec }): JSX.Element {
    const productName = spec.project_brief.product_name.text || spec.project_name
    const tagline = spec.project_brief.one_line_value_prop.text
    const persona = spec.project_brief.primary_persona
    const pains = spec.project_brief.top_user_pains.slice(0, 3)
    const features = spec.project_brief.top_features.slice(0, 6)
    const proofPoints = spec.project_brief.proof_points.slice(0, 4)
    const tldr0 = spec.tldr[0]

    return (
        <div className="flex flex-col text-[14px] text-slate-800 font-sans max-h-[640px] overflow-y-auto">
            <nav className="px-8 py-4 flex items-center justify-between border-b border-slate-100 shrink-0">
                <span className="font-semibold text-slate-900">{productName}</span>
                <div className="hidden sm:flex items-center gap-4 text-slate-500 text-[13px]">
                    <span>Features</span>
                    <span>Pricing</span>
                    <span>Docs</span>
                    <span className="px-3 py-1.5 rounded-md bg-slate-900 text-white font-medium">Get started</span>
                </div>
            </nav>

            <section className="px-8 py-16 text-center bg-gradient-to-b from-slate-50 to-white">
                <h1 className="text-3xl md:text-4xl font-bold leading-tight max-w-3xl mx-auto text-slate-900">
                    {tagline || productName}
                </h1>
                {persona.label && (
                    <p className="mt-4 text-slate-600 max-w-xl mx-auto">
                        For {persona.label}
                        {persona.description ? ` — ${persona.description}` : ''}
                    </p>
                )}
                <div className="mt-7 flex items-center justify-center gap-2 flex-wrap">
                    <span className="px-4 py-2 rounded-md bg-slate-900 text-white font-medium text-sm">
                        Get started free
                    </span>
                    <span className="px-4 py-2 rounded-md border border-slate-200 text-slate-700 font-medium text-sm">
                        See how it works
                    </span>
                </div>
            </section>

            {pains.length > 0 && (
                <section className="px-8 py-12 border-t border-slate-100">
                    <h2 className="text-xl font-semibold text-center text-slate-900">
                        Built for the headaches you actually have
                    </h2>
                    <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4 max-w-4xl mx-auto">
                        {pains.map((pain) => (
                            <div key={pain.label} className="p-5 rounded-lg border border-slate-100 bg-white">
                                <div className="font-medium text-slate-900">{pain.label}</div>
                                <p className="mt-1.5 text-slate-600 text-[13px] leading-relaxed">{pain.description}</p>
                            </div>
                        ))}
                    </div>
                </section>
            )}

            {features.length > 0 && (
                <section className="px-8 py-12 bg-slate-50 border-t border-slate-100">
                    <h2 className="text-xl font-semibold text-center text-slate-900">What you get</h2>
                    <ul className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl mx-auto list-none p-0">
                        {features.map((feature) => (
                            <li key={feature} className="flex items-start gap-2 text-[13px]">
                                <span className="text-emerald-500 mt-0.5 shrink-0">✓</span>
                                <span>{feature}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {proofPoints.length > 0 && (
                <section className="px-8 py-12 border-t border-slate-100">
                    <h2 className="text-xl font-semibold text-center text-slate-900">Why teams trust {productName}</h2>
                    <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl mx-auto">
                        {proofPoints.map((p, i) => (
                            <blockquote
                                key={`${p.kind}-${i}`}
                                className="p-5 rounded-lg border border-slate-100 bg-white m-0"
                            >
                                <p className="text-slate-700 m-0">{p.statement}</p>
                                <div className="mt-2 text-[11px] uppercase tracking-wide text-slate-400">{p.kind}</div>
                            </blockquote>
                        ))}
                    </div>
                </section>
            )}

            <section className="px-8 py-12 bg-slate-900 text-white text-center border-t border-slate-100">
                <h2 className="text-2xl font-bold">Ready to try {productName}?</h2>
                {tldr0 && <p className="mt-3 text-slate-300 max-w-xl mx-auto">{tldr0}</p>}
                <span className="mt-6 inline-block px-5 py-2.5 rounded-md bg-white text-slate-900 font-medium text-sm">
                    Start free
                </span>
            </section>

            <footer className="px-8 py-4 text-[11px] text-slate-400 text-center border-t border-slate-100 shrink-0">
                © {productName} — built with PostHog Founder Mode
            </footer>
        </div>
    )
}

function slugify(s: string): string {
    return (
        s
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 40) || 'your-product'
    )
}

function escapeHtml(s: string): string {
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
}

export function renderLandingPageHtml(spec: LandingPageBuildSpec): string {
    const productName = escapeHtml(spec.project_brief.product_name.text || spec.project_name)
    const tagline = escapeHtml(spec.project_brief.one_line_value_prop.text || '')
    const personaLabel = escapeHtml(spec.project_brief.primary_persona.label || '')
    const personaDescription = escapeHtml(spec.project_brief.primary_persona.description || '')
    const tldr0 = escapeHtml(spec.tldr[0] || '')
    const seoTitle = escapeHtml(spec.seo_front_matter.title || spec.project_name)
    const seoDescription = escapeHtml(spec.seo_front_matter.description || tagline)

    const personaLine =
        personaLabel || personaDescription
            ? `<p class="hero-sub">For ${personaLabel}${personaDescription ? ` — ${personaDescription}` : ''}</p>`
            : ''

    const painHtml = spec.project_brief.top_user_pains
        .slice(0, 3)
        .map(
            (p) => `
            <div class="card">
                <h3>${escapeHtml(p.label)}</h3>
                <p>${escapeHtml(p.description)}</p>
            </div>`
        )
        .join('')

    const featureHtml = spec.project_brief.top_features
        .slice(0, 6)
        .map((f) => `<li>${escapeHtml(f)}</li>`)
        .join('')

    const proofHtml = spec.project_brief.proof_points
        .slice(0, 4)
        .map(
            (p) => `
            <blockquote>
                <p>${escapeHtml(p.statement)}</p>
                <span>${escapeHtml(p.kind)}</span>
            </blockquote>`
        )
        .join('')

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${seoTitle}</title>
    <meta name="description" content="${seoDescription}" />
    <style>
        :root { color-scheme: light; }
        * { box-sizing: border-box; }
        html, body { margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, system-ui, sans-serif;
            color: #0f172a;
            background: #fff;
            line-height: 1.5;
        }
        nav {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 32px;
            border-bottom: 1px solid #f1f5f9;
        }
        nav .brand { font-weight: 600; }
        nav .links {
            display: flex;
            gap: 16px;
            color: #64748b;
            font-size: 14px;
            align-items: center;
        }
        nav .cta-small {
            background: #0f172a;
            color: #fff;
            padding: 6px 14px;
            border-radius: 6px;
            font-weight: 500;
        }
        section { padding: 64px 32px; }
        .hero {
            background: linear-gradient(to bottom, #f8fafc, #fff);
            text-align: center;
        }
        .hero h1 {
            font-size: 40px;
            font-weight: 700;
            max-width: 720px;
            margin: 0 auto;
            line-height: 1.15;
            color: #0f172a;
        }
        .hero-sub {
            margin: 18px auto 0;
            color: #475569;
            max-width: 560px;
        }
        .hero .ctas {
            margin-top: 28px;
            display: inline-flex;
            gap: 8px;
        }
        .hero button {
            padding: 10px 18px;
            border-radius: 6px;
            font-weight: 500;
            font-size: 14px;
            cursor: pointer;
            border: none;
        }
        .hero .primary { background: #0f172a; color: #fff; }
        .hero .secondary {
            background: #fff;
            color: #334155;
            border: 1px solid #e2e8f0;
        }
        h2 {
            font-size: 22px;
            font-weight: 600;
            text-align: center;
            margin: 0;
            color: #0f172a;
        }
        .grid-3 {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            max-width: 960px;
            margin: 32px auto 0;
        }
        .card {
            padding: 20px;
            border: 1px solid #f1f5f9;
            border-radius: 8px;
            background: #fff;
        }
        .card h3 { margin: 0 0 8px; font-size: 15px; }
        .card p { margin: 0; color: #475569; font-size: 13px; }
        .features { background: #f8fafc; border-top: 1px solid #f1f5f9; }
        .features ul {
            list-style: none;
            padding: 0;
            margin: 32px auto 0;
            max-width: 640px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }
        .features li {
            display: flex;
            gap: 8px;
            font-size: 14px;
        }
        .features li::before { content: '✓'; color: #10b981; }
        .proof { border-top: 1px solid #f1f5f9; }
        .proof-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            max-width: 800px;
            margin: 32px auto 0;
        }
        blockquote {
            margin: 0;
            padding: 20px;
            border: 1px solid #f1f5f9;
            border-radius: 8px;
            background: #fff;
        }
        blockquote p { margin: 0; color: #334155; }
        blockquote span {
            display: block;
            margin-top: 8px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #94a3b8;
        }
        .cta-footer {
            background: #0f172a;
            color: #fff;
            text-align: center;
            border-top: 1px solid #f1f5f9;
        }
        .cta-footer h2 { color: #fff; font-size: 28px; font-weight: 700; }
        .cta-footer p {
            color: #cbd5e1;
            max-width: 560px;
            margin: 12px auto 0;
        }
        .cta-footer button {
            margin-top: 28px;
            padding: 12px 22px;
            border-radius: 6px;
            background: #fff;
            color: #0f172a;
            font-weight: 500;
            border: none;
            cursor: pointer;
        }
        footer {
            padding: 18px 32px;
            text-align: center;
            font-size: 11px;
            color: #94a3b8;
            border-top: 1px solid #f1f5f9;
        }
        @media (max-width: 640px) {
            section { padding: 40px 20px; }
            .hero h1 { font-size: 28px; }
            .features ul { grid-template-columns: 1fr; }
            .proof-grid { grid-template-columns: 1fr; }
            nav .links { display: none; }
        }
    </style>
</head>
<body>
    <nav>
        <span class="brand">${productName}</span>
        <div class="links">
            <span>Features</span>
            <span>Pricing</span>
            <span>Docs</span>
            <span class="cta-small">Get started</span>
        </div>
    </nav>
    <section class="hero">
        <h1>${tagline || productName}</h1>
        ${personaLine}
        <div class="ctas">
            <button class="primary">Get started free</button>
            <button class="secondary">See how it works</button>
        </div>
    </section>
    ${painHtml ? `<section><h2>Built for the headaches you actually have</h2><div class="grid-3">${painHtml}</div></section>` : ''}
    ${featureHtml ? `<section class="features"><h2>What you get</h2><ul>${featureHtml}</ul></section>` : ''}
    ${proofHtml ? `<section class="proof"><h2>Why teams trust ${productName}</h2><div class="proof-grid">${proofHtml}</div></section>` : ''}
    <section class="cta-footer">
        <h2>Ready to try ${productName}?</h2>
        ${tldr0 ? `<p>${tldr0}</p>` : ''}
        <button>Start free</button>
    </section>
    <footer>© ${productName} — mockup generated by PostHog Founder Mode</footer>
</body>
</html>`
}
