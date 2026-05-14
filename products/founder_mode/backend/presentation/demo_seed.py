"""Demo seed payload for the FounderProject viewset's seed_demo action.

A realistic-looking, fully-populated set of stage envelopes. Lets a developer skip the
whole LLM-driven flow and immediately exercise the downstream surfaces (workspace,
landing-page mockup, PostHog stack recommendations). Not used in production — the
seed_demo action only fires when settings.DEBUG is True.
"""

from typing import Any


def build_demo_payload() -> dict[str, Any]:
    """Return a kwargs dict for FounderProject.objects.create(team=..., created_by=..., **payload)."""
    return {
        "name": "Founder Mode demo project",
        "current_step": "marketing",
        "ideation": {
            "idea": "A guided cofounder that walks first-time founders from idea to validated launch artifacts in one afternoon.",
            "problem": "Founders waste weeks shaping vague ideas into something testable. They jump to building before they know what they're building.",
            "what": "Step-by-step chat that fills a lean canvas, runs a validation pass, drafts a landing page spec, and proposes a GTM plan.",
            "how": "Five LLM-driven stages (ideation, validation, GTM, MVP, marketing) each producing a structured artifact written to a per-stage JSON column.",
            "who": "First-time solo founders in the first 90 days of an idea, already familiar with PostHog from prior projects.",
        },
        "validation": {
            "status": "completed",
            "report": {
                "verdict": {
                    "score": 7,
                    "confidence": "medium",
                    "rationale": "Founders in early ideation are a real and underserved segment, and PostHog has direct distribution. The risk is that LLM-drafted artifacts feel generic — quality of the output is what makes or breaks adoption.",
                },
                "competitors": [
                    {
                        "name": "v0 by Vercel",
                        "positioning": "Generates working UI from natural language prompts.",
                        "description": "Strong on production-grade scaffolding but doesn't help shape the underlying idea or validate the market.",
                        "url": "https://v0.dev",
                    },
                    {
                        "name": "Lovable",
                        "positioning": "Build full-stack apps with AI conversations.",
                        "description": "Targets the build phase, not the shape-the-idea phase. Overlaps on landing-page generation but assumes the founder already knows what to build.",
                        "url": "https://lovable.dev",
                    },
                    {
                        "name": "Y Combinator's startup school",
                        "positioning": "Free curriculum for first-time founders.",
                        "description": "Trusted brand and great content, but linear and non-interactive — doesn't produce founder-specific artifacts.",
                        "url": "https://startupschool.org",
                    },
                ],
                "differentiation": {
                    "summary": "Founder Mode is the only tool that ends with a complete set of launchable artifacts — landing page, GTM plan, MVP spec, marketing playbook — derived from a structured idea-shaping chat, not just code.",
                    "moat": "PostHog's existing founder audience and product-analytics integration. The workspace is an in-product artifact surface that competitors would have to rebuild from scratch.",
                },
            },
        },
        "gtm": {
            "status": "completed",
            "result": {
                "positioning_statement": "For first-time founders in the first 90 days of an idea, Founder Mode is the guided cofounder that turns vague ideas into validated, ship-ready artifacts in a single afternoon — without the boilerplate of generic AI-coding tools.",
                "primary_segment": {
                    "name": "First-time solo founders",
                    "description": "Engineers or PMs at established companies who are exploring leaving to start something, and want a structured way to pressure-test the idea before committing.",
                },
                "moat": "Distribution through PostHog's existing founder audience + tight integration with the rest of the PostHog product. The workspace becomes the founder's home and pulls them deeper into PostHog.",
                "pricing_philosophy": "Bundled with the PostHog seat — no separate SKU. Free during the founder's first 90 days, then upsell to standard PostHog tiers once they're shipping product.",
                "primary_channel": "PostHog community Slack",
                "secondary_channels": [
                    "IndieHackers long-form posts",
                    "X / Twitter founder accounts",
                    "Show HN once polished",
                    "Founder-focused podcasts",
                ],
            },
        },
        "mvp": {
            "status": "completed",
            "result": {
                "one_liner": "A chat-driven flow that produces a lean canvas, validation report, landing page spec, MVP plan, and marketing playbook — all stored as markdown pages in an in-product workspace.",
                "core_flow": [
                    {
                        "step": 1,
                        "user_action": "Start the cofounder chat",
                        "system_response": "Streams topic-scoped questions until the lean canvas is complete",
                        "success_signal": "Canvas saved as a `FounderProject` row with all slots filled",
                    },
                    {
                        "step": 2,
                        "user_action": "Watch validation run",
                        "system_response": "Two-pass Gemini call returns competitor research + verdict",
                        "success_signal": "Validation report renders with a score, confidence level, and named competitors",
                    },
                    {
                        "step": 3,
                        "user_action": "Review GTM plan and MVP spec",
                        "system_response": "Stages 3 and 4 generate positioning + happy-path",
                        "success_signal": "GTM and MVP envelopes both end in `completed` state",
                    },
                    {
                        "step": 4,
                        "user_action": "Generate landing page + marketing plan",
                        "system_response": "Stage 5 generates a full build spec and a launch playbook in parallel",
                        "success_signal": "Marketing page spec includes copy hooks, brand decisions, and PostHog events",
                    },
                    {
                        "step": 5,
                        "user_action": "Open the workspace",
                        "system_response": "Renders every stage's data as a Markdown page tree",
                        "success_signal": "Founder reads the artifacts and either accepts or hits 'redo' on a stage",
                    },
                ],
                "must_haves": [
                    "Five-stage LLM flow with structured outputs (Pydantic-validated)",
                    "Workspace renders pages directly from the project JSON",
                    "Landing page mockup with a brand-styled preview",
                    "PostHog stack recommendations derived from the build spec",
                    "Step-by-step debug menu so anyone can jump to any stage",
                ],
                "deliberately_excluded": [
                    "Multi-project per team — one founder, one project for v1",
                    "Exporting workspace to Notion / Obsidian",
                    "Real-time collaboration with a co-founder",
                    "Persisting workspace edits to the DB (in-memory only for now)",
                    "Custom prompts — every stage uses a fixed system prompt for v1",
                ],
            },
        },
        "marketing_page": {
            "status": "completed",
            "page": _demo_landing_page_spec(),
        },
        "marketing_steps": {
            "status": "completed",
            "result": {
                "launch_summary": "Soft-launch in the PostHog community Slack on day one, then expand to IndieHackers and X over the first week. Lead every post with the *artifacts*, not the AI — concrete deliverables are the differentiator vs. v0/Lovable.",
                "target_communities": [
                    "PostHog community Slack",
                    "IndieHackers",
                    "X / Twitter founder accounts",
                    "Show HN",
                    "r/SideProject",
                    "Founder-focused podcasts",
                ],
                "steps": [
                    {
                        "title": "Tease the workspace",
                        "description": "Two days before launch, drop a screenshot of the workspace in the PostHog community with the line 'Coming Friday' — no product link.",
                        "channel": "PostHog community Slack",
                        "timeline": "D-2",
                        "ready_to_use_content": [
                            {
                                "platform": "linkedin",
                                "content": "Spent the week building something we've wanted for a while: a guided cofounder for first-time founders. It takes you from a fuzzy idea to a validated landing page in one afternoon — with a workspace at the end that holds everything you produced.\n\nNo more abandoned Notion docs. No more 'I'll validate it later.' Just artifacts you can ship.\n\nDropping in PostHog on Friday. DM me if you want early access.",
                                "tips": "Use this 48 hours before launch. Don't link the product yet — drive replies, build the list.",
                            },
                            {
                                "platform": "twitter",
                                "content": "founder mode → built a guided cofounder that takes you from messy idea to launch-ready landing page in an afternoon\n\nworkspace at the end with every artifact, brand-styled mockup, posthog stack pre-wired\n\nin posthog friday, mostly because someone has to do it",
                                "tips": "Lowercase + dry voice — matches the audience. Don't add hashtags.",
                            },
                        ],
                    },
                    {
                        "title": "Launch in the community",
                        "description": "Friday morning post in the PostHog community Slack with a 60-second screen recording of the full flow.",
                        "channel": "PostHog community Slack",
                        "timeline": "Launch day",
                        "ready_to_use_content": [
                            {
                                "platform": "linkedin",
                                "content": "Founder Mode is live in PostHog.\n\nWhat it does:\n- Chat-driven idea shaping that produces a lean canvas\n- Automated validation pass with competitor research\n- Full landing page build spec (copy, brand, sections, events)\n- Marketing playbook with ready-to-post content for every channel\n\nAll artifacts live in an in-product workspace. Built in a week as a hackathon project — feedback welcome.\n\nLink: posthog.com/founder",
                                "tips": "Pin in your profile for 24 hours. Watch comments for testimonials to reuse next week.",
                            },
                            {
                                "platform": "product_hunt",
                                "content": "Founder Mode for PostHog — the guided cofounder for first-time founders.\n\nGo from messy idea to launch-ready artifacts in one afternoon. Five LLM stages (ideation, validation, GTM, MVP, marketing) each produce a real, structured deliverable. Workspace holds it all in markdown. Pre-wires the PostHog stack for the launch.\n\nFree with any PostHog account.",
                                "tips": "Schedule for a Tuesday morning PST launch. Have 5 hunters lined up the night before.",
                            },
                        ],
                    },
                    {
                        "title": "Long-form on IndieHackers",
                        "description": "Write the meta-post: 'I used Founder Mode to validate Founder Mode' — show the actual artifacts produced.",
                        "channel": "IndieHackers",
                        "timeline": "D+3",
                        "ready_to_use_content": [
                            {
                                "platform": "indie_hackers",
                                "content": "I used Founder Mode to validate Founder Mode\n\nThe meta is the message. Here's the lean canvas, validation report, and landing page spec it produced — without me writing a single prompt.\n\n[paste screenshots of the workspace]\n\nVerdict score was 7/10 with medium confidence. The differentiation note nailed something I'd been struggling to articulate: artifacts, not code. That's what makes this different from v0 or Lovable.\n\nWhat surprised me about the validation pass: it called out my own competitor blind spot. I hadn't realized YC Startup School was technically a competitor until the report flagged it.",
                                "tips": "Lead with the meta. End with the surprise — that's the share-worthy moment.",
                            }
                        ],
                    },
                    {
                        "title": "Show HN",
                        "description": "Once 50+ people have used it and you have 2-3 testimonials, post Show HN with a focus on the technical approach (5 LLM stages, structured outputs, etc.).",
                        "channel": "Hacker News",
                        "timeline": "D+7",
                        "ready_to_use_content": [
                            {
                                "platform": "hacker_news",
                                "content": "Show HN: Founder Mode — a guided cofounder that produces real launch artifacts\n\nWe built this because every AI tool we tried either skipped the idea-shaping phase entirely (v0, Lovable) or stopped at a summary (ChatGPT, Claude). The gap was structured artifacts — a lean canvas, a validated brief, a landing-page spec — that you can actually take to a developer or feed back into another AI coding agent.\n\nFive-stage LLM flow, each stage producing a Pydantic-validated structured output. Workspace renders the outputs as a markdown wiki. Pre-wires the PostHog stack (events, surveys, feature flags) so you can ship measurable from day one.\n\nCode: github.com/posthog/posthog (look in products/founder_mode)\nLive: posthog.com/founder",
                                "tips": "Post Tuesday 8am PT. Be in the comments for the first 4 hours — that's when the post lives or dies.",
                            }
                        ],
                    },
                ],
            },
        },
    }


def _demo_landing_page_spec() -> dict[str, Any]:
    """Realistic LandingPageBuildSpec — mirrors the frontend MOCK_BUILD_SPEC shape."""
    return {
        "project_name": "Founder Mode",
        "tldr": [
            "Go from messy idea to launch-ready landing page in one afternoon.",
            "Guided chat fills your lean canvas, validates assumptions, and writes the build spec.",
            "Hand the spec to an AI coding agent and ship.",
        ],
        "project_brief": {
            "product_name": {"text": "Founder Mode", "sources": []},
            "one_line_value_prop": {"text": "From idea to launch artifacts in one afternoon.", "sources": []},
            "primary_persona": {
                "label": "first-time solo founders",
                "description": "in the first 90 days of an idea, still shaping what to build",
                "sources": [],
            },
            "secondary_persona": None,
            "top_user_pains": [
                {
                    "label": "Stuck before the first line of code",
                    "description": "Three abandoned Notion docs about the same idea. No version feels committable.",
                    "quantitative_evidence": None,
                    "sources": [],
                },
                {
                    "label": "Validation is hand-wavy",
                    "description": "You know you should pressure-test assumptions, but you skip it and start building anyway.",
                    "quantitative_evidence": None,
                    "sources": [],
                },
                {
                    "label": "Landing pages are a slog",
                    "description": "You can build the product but you can't bear writing the copy or designing the page.",
                    "quantitative_evidence": None,
                    "sources": [],
                },
            ],
            "top_features": [
                "Guided lean canvas chat",
                "Automated validation pass",
                "AI-generated landing page build spec",
                "GTM plan generator",
                "PostHog instrumentation included",
                "Markdown export for any AI coding agent",
            ],
            "proof_points": [
                {
                    "kind": "qualitative",
                    "statement": '"I went from a vague Notion doc to a published landing page in a single afternoon."',
                    "sources": [],
                },
                {
                    "kind": "quantitative",
                    "statement": "4 out of 5 founders interviewed said they would use this in week one of a new idea.",
                    "sources": [],
                },
                {
                    "kind": "qualitative",
                    "statement": '"Don\'t give me a summary — give me artifacts I can ship. This does that."',
                    "sources": [],
                },
                {
                    "kind": "quantitative",
                    "statement": "Average time from idea to first published landing page: 1 working day.",
                    "sources": [],
                },
            ],
        },
        "brand": {
            "source": "synthesized",
            "tone": {"text": "Direct, founder-to-founder, no fluff.", "sources": []},
            "voice": {"text": "Confident, pragmatic, occasionally dry.", "sources": []},
            "palette": {"text": "Slate neutrals with a single emerald accent for affirmation.", "sources": []},
            "typography": {
                "text": "System sans-serif, tight headings, generous line height in body.",
                "sources": [],
            },
            "imagery": {
                "text": "Screenshots of the artifacts being produced, not abstract illustrations.",
                "sources": [],
            },
            "references": {"text": "Linear, Vercel, Resend — sharp, opinionated tool aesthetics.", "sources": []},
            "anti_references": {
                "text": "Generic SaaS hero illustrations, AI-themed gradients, stock photography.",
                "sources": [],
            },
        },
        "seo_keywords": [
            {"phrase": "idea to launch", "priority": "high", "sources": []},
            {"phrase": "AI cofounder", "priority": "high", "sources": []},
            {"phrase": "lean canvas generator", "priority": "medium", "sources": []},
            {"phrase": "landing page for founders", "priority": "medium", "sources": []},
        ],
        "competitor_profiles": [],
        "coverage_gaps": [],
        "page_sections": [
            {
                "number": 1,
                "name": "Hero",
                "classification": "core",
                "why_included": None,
                "purpose": "Land the value prop and get to a CTA in under 6 seconds.",
                "copy_hooks": "From idea to launch artifacts in one afternoon.",
                "design_notes": "Centered hero, gradient wash, two CTAs.",
                "component_recipe": "Standard hero with primary + secondary button.",
                "posthog_events": ["$pageview", "hero_cta_clicked", "hero_secondary_clicked"],
                "acceptance_criteria": ["Headline visible without scroll on 1280×800."],
            },
            {
                "number": 2,
                "name": "Pain points",
                "classification": "core",
                "why_included": None,
                "purpose": "Earn trust by naming the problems out loud.",
                "copy_hooks": "Built for the headaches you actually have.",
                "design_notes": "3-up card grid, neutral background.",
                "component_recipe": "Card grid component.",
                "posthog_events": ["pain_card_viewed"],
                "acceptance_criteria": ["Three cards visible on desktop, stack on mobile."],
            },
            {
                "number": 3,
                "name": "Pricing teaser",
                "classification": "optional_included",
                "why_included": "Founder persona expects upfront pricing.",
                "purpose": 'Pre-empt the "is this free?" objection.',
                "copy_hooks": "Bundled with your PostHog seat.",
                "design_notes": "Single tier, no comparison table for v1.",
                "component_recipe": "Single pricing card.",
                "posthog_events": ["pricing_viewed", "pricing_signup_clicked"],
                "acceptance_criteria": ["Pricing CTA scrolls to signup form."],
            },
            {
                "number": 4,
                "name": "Footer CTA",
                "classification": "core",
                "why_included": None,
                "purpose": "Catch visitors who scrolled past hero.",
                "copy_hooks": "Ready to try Founder Mode?",
                "design_notes": "Inverted color, full-width.",
                "component_recipe": "Wide CTA band.",
                "posthog_events": ["footer_cta_clicked", "signup_started"],
                "acceptance_criteria": ["Button always above the fold on viewport reaches."],
            },
        ],
        "skipped_sections": [],
        "seo_front_matter": {
            "title": "Founder Mode — from idea to launch artifacts in one afternoon",
            "description": "Guided cofounder that walks you from lean canvas to validated landing page brief, end-to-end.",
            "og_image_alt": None,
            "json_ld_type": "Product",
        },
        "performance_floor": {
            "lcp_max_seconds": 2.5,
            "cls_max": 0.1,
            "lighthouse_a11y_min": 95,
            "notes": [],
        },
        "instrumentation": {
            "sdk_install_cmd": "pnpm add posthog-js",
            "init_notes": [
                "Call posthog.init in your root layout.",
                "Enable session_recording for landing page route.",
            ],
            "identify_notes": ["Identify users on signup_success with their email."],
            "custom_events": [
                {"name": "hero_cta_clicked", "when": "Primary hero CTA pressed.", "properties": ["variant", "persona"]},
                {"name": "signup_started", "when": "Signup form mounted in view.", "properties": ["source_section"]},
            ],
            "privacy_notes": ["Mask form inputs in session recordings."],
        },
        "global_acceptance_criteria": [
            {"statement": "LCP under 2.5s on mobile."},
            {"statement": "All CTAs fire a PostHog event with `source_section` property."},
        ],
    }
