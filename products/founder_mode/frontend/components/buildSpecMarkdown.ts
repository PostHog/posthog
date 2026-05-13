import type {
    BrandDirection,
    CompetitorPositioning,
    CoverageGap,
    GlobalAcceptanceCriterion,
    InstrumentationGuide,
    LandingPageBuildSpec,
    PageSection,
    Persona,
    ProjectBrief,
    SEOKeyword,
    SkippedSection,
    SourcedText,
    UserPain,
} from './founderLandingPageLogic'

// Renders a LandingPageBuildSpec into the markdown shape the founder downloads / shares.
// Mirrors the canonical example the team agreed on so output stays consistent.

const HR = '\n\n---\n\n'

export function renderBuildSpecMarkdown(spec: LandingPageBuildSpec): string {
    const parts: string[] = [
        `# Landing page build spec — ${spec.project_name}`,
        '',
        '## TL;DR',
        '',
        spec.tldr.map((b) => `- ${b}`).join('\n'),
        HR.trim(),
        renderProjectBrief(spec.project_brief),
        HR.trim(),
        renderBrand(spec.brand),
        HR.trim(),
        renderSEO(spec.seo_keywords, spec.competitor_profiles, spec.coverage_gaps),
        HR.trim(),
        renderPageStructure(spec.page_sections, spec.skipped_sections, spec.seo_front_matter, spec.performance_floor),
        HR.trim(),
        renderInstrumentation(spec.instrumentation),
        HR.trim(),
        renderAcceptance(spec.global_acceptance_criteria),
    ]
    return parts.filter(Boolean).join('\n\n')
}

// ---------- helpers ----------------------------------------------------------

function sourceTag(sources: string[]): string {
    return `\`[source: ${sources.join(', ')}]\``
}

function sourced(s: SourcedText): string {
    return `${s.text} ${sourceTag(s.sources)}`
}

function persona(label: string, p: Persona): string {
    return `- **${label}:** ${p.description} ${sourceTag(p.sources)}`
}

function userPain(p: UserPain): string {
    const evidence = p.quantitative_evidence ? ` — ${p.quantitative_evidence}` : ''
    return `- **${p.label}.** ${p.description}${evidence} ${sourceTag(p.sources)}`
}

// ---------- sections --------------------------------------------------------

function renderProjectBrief(brief: ProjectBrief): string {
    const personas = [persona('Primary ICP', brief.primary_persona)]
    if (brief.secondary_persona) {
        personas.push(persona('Secondary', brief.secondary_persona))
    }
    return [
        '## Project brief',
        '',
        `- **Product name:** ${sourced(brief.product_name)}`,
        `- **One-line value prop:** "${sourced(brief.one_line_value_prop)}"`,
        '- **Target ICP:**',
        ...personas.map((line) => `  ${line.replace(/^- /, '- ')}`),
        '- **Top user pains:**',
        ...brief.top_user_pains.map((p) => `  ${userPain(p).replace(/^- /, '- ')}`),
        '- **Top features (in order of pull):**',
        ...brief.top_features.map((f) => `  - ${f}`),
        '- **Proof points:**',
        ...brief.proof_points.map((pp) => `  - ${pp.statement} ${sourceTag(pp.sources)}`),
    ].join('\n')
}

function renderBrand(brand: BrandDirection): string {
    return [
        '## Brand decisions',
        '',
        `> \`brand.source: "${brand.source}"\``,
        '',
        `- **Tone:** ${sourced(brand.tone)}`,
        `- **Voice:** ${sourced(brand.voice)}`,
        `- **Palette:** ${sourced(brand.palette)}`,
        `- **Typography:** ${sourced(brand.typography)}`,
        `- **Imagery:** ${sourced(brand.imagery)}`,
        `- **References:** ${sourced(brand.references)}`,
        `- **Anti-references:** ${sourced(brand.anti_references)}`,
    ].join('\n')
}

function renderSEO(keywords: SEOKeyword[], competitors: CompetitorPositioning[], gaps: CoverageGap[]): string {
    const sorted = [...keywords].sort((a, b) => priorityRank(b.priority) - priorityRank(a.priority))
    const tableRows = sorted.map((k) => `| \`${k.phrase}\` | ${k.sources.join(' · ')} | **${k.priority}** |`)
    const competitorBlocks = competitors.map((c) =>
        [
            `**${c.name}** — \`${c.url}\` — pages fetched: ${c.pages_fetched.map((p) => `\`${p}\``).join(', ')}`,
            `Positioning: ${c.positioning}`,
            `ICP: ${c.icp}`,
            `Pricing: ${c.pricing}`,
            `CTA: "${c.cta}"`,
            `Voice notes: ${c.voice_notes}`,
        ].join('\n')
    )
    const gapBlock = gaps.length
        ? '\n> ⚠️ **Coverage gaps:**\n' +
          gaps.map((g) => `> - ${g.competitor}${g.url ? ` (${g.url})` : ''} — ${g.reason}`).join('\n')
        : ''

    return [
        '## SEO keywords',
        '',
        '| Phrase | Sources | Priority |',
        '|---|---|---|',
        ...tableRows,
        '',
        '### Per-competitor positioning',
        '',
        ...competitorBlocks,
        gapBlock,
    ]
        .filter(Boolean)
        .join('\n')
}

function priorityRank(p: SEOKeyword['priority']): number {
    return p === 'high' ? 2 : p === 'medium' ? 1 : 0
}

function renderPageStructure(
    sections: PageSection[],
    skipped: SkippedSection[],
    seo: LandingPageBuildSpec['seo_front_matter'],
    perf: LandingPageBuildSpec['performance_floor']
): string {
    const ordered = [...sections].sort((a, b) => a.number - b.number)
    const sectionBlocks = ordered.map((s) => renderSection(s))
    const skippedBlock = skipped.length
        ? ['', '### Skipped sections', '', ...skipped.map((s) => `- **${s.name} — skipped.** ${s.reason}`)].join('\n')
        : ''
    const seoBlock = [
        '',
        '### SEO front-matter',
        '',
        `- \`<title>\` "${seo.title}"`,
        `- \`<meta name="description">\` "${seo.description}"`,
        seo.og_image_alt ? `- \`og:image\` alt: "${seo.og_image_alt}"` : null,
        `- JSON-LD: \`${seo.json_ld_type}\``,
    ]
        .filter(Boolean)
        .join('\n')
    const perfBlock = [
        '',
        '### Performance + accessibility floor',
        '',
        `- LCP < ${perf.lcp_max_seconds}s on simulated 4G`,
        `- CLS < ${perf.cls_max}`,
        `- Lighthouse a11y ≥ ${perf.lighthouse_a11y_min}`,
        ...perf.notes.map((n) => `- ${n}`),
    ].join('\n')

    return ['## Page structure', '', ...sectionBlocks, skippedBlock, seoBlock, perfBlock].filter(Boolean).join('\n')
}

function renderSection(s: PageSection): string {
    const tag = s.classification === 'core' ? '`[core]`' : '`[optional — included]`'
    const why = s.why_included ? `\n> **Why included:** ${s.why_included}\n` : ''
    const events = s.posthog_events.length
        ? `\n- **PostHog events:** ${s.posthog_events.map((e) => `\`${e}\``).join(', ')}`
        : '\n- **PostHog events:** autocapture only'
    const acs = s.acceptance_criteria.map((a) => `  - ${a}`).join('\n')
    return [
        `### ${s.number}. ${s.name} ${tag}`,
        why,
        `- **Purpose:** ${s.purpose}`,
        `- **Copy hooks:**\n${indent(s.copy_hooks)}`,
        `- **Design notes:**\n${indent(s.design_notes)}`,
        `- **Component recipe:**\n${indent(s.component_recipe)}`,
        events,
        `- **Acceptance criteria:**\n${acs}`,
    ]
        .filter(Boolean)
        .join('\n')
}

function indent(s: string): string {
    return s
        .split('\n')
        .map((line) => `  ${line}`)
        .join('\n')
}

function renderInstrumentation(inst: InstrumentationGuide): string {
    const eventRows = inst.custom_events.map(
        (e) => `| \`${e.name}\` | ${e.when} | ${e.properties.map((p) => `\`${p}\``).join(', ')} |`
    )
    return [
        '## PostHog instrumentation',
        '',
        '### SDK install',
        '',
        '```bash',
        inst.sdk_install_cmd,
        '```',
        '',
        '### Init notes',
        '',
        ...inst.init_notes.map((n) => `- ${n}`),
        '',
        '### Identify',
        '',
        ...inst.identify_notes.map((n) => `- ${n}`),
        '',
        '### Custom events',
        '',
        '| Event | Fires when | Properties |',
        '|---|---|---|',
        ...eventRows,
        inst.privacy_notes.length ? '\n### Privacy\n' : '',
        ...inst.privacy_notes.map((n) => `- ${n}`),
    ]
        .filter(Boolean)
        .join('\n')
}

function renderAcceptance(criteria: GlobalAcceptanceCriterion[]): string {
    return ['## Acceptance criteria (global)', '', ...criteria.map((c) => `- ${c.statement}`)].join('\n')
}
