# Web vitals: causes and remediations

Read this when you're about to write a finding. Every reported web vitals finding must
carry two things this file gives you: a **metric-specific cause hypothesis** (why the
value is likely what it is) and a **concrete remediation** (what would move it). Pick the
cause that fits the evidence you have — don't list all of them; name the one the data
points at and say what you'd check to confirm.

## Diagnose before you attribute

The p75 value tells you _that_ a page is slow, not _why_. Before settling on a cause,
slice the same `$web_vitals` data:

- **By `$device_type`** — mobile p75 is routinely 2–3× desktop (slower CPUs, networks). A
  page that's "poor" only because its mobile share grew is a composition story, not a code
  regression. Report the split.
- **By `$geoip_country_code`** — a page slow only for distant regions points at
  origin/CDN distance, not page code.
- **By `$browser`** — a regression isolated to one engine is often a polyfill, a CSS
  feature, or a JS API doing extra work there.
- **For a regression, date the onset** with a daily p75 series and line it up against
  `activity-log-list`. "Stepped on {day}, consistent with a deploy" is the most actionable
  framing — but you usually can't see their releases, so frame it as correlation to confirm.

A regression that holds across every device/region/browser slice is a real shared cause
(a deploy, a CDN/edge change, a global third-party tag). A "regression" that lives in one
slice is usually a population mix change — say so and lower the severity.

## LCP — Largest Contentful Paint (load)

Time until the largest above-the-fold element (usually the hero image, a big heading, or a
video poster) renders. Bands: good ≤ 2500ms, poor > 4000ms.

**Common causes**

- Slow server response / TTFB — the document itself is late, so everything downstream is.
- Render-blocking CSS or JS in `<head>` delaying first paint.
- The LCP element is a large, unoptimized, or un-preloaded image (or lazy-loaded by
  mistake, so it isn't fetched until late).
- Client-side rendering: the hero is painted by JS after hydration rather than in the HTML.
- A web font blocking text render of an LCP text element.

**Remediations**

- Cut TTFB: cache the document at the edge/CDN, fix slow origin queries, use SSR/streaming.
- `<link rel="preload">` the LCP image (or `fetchpriority="high"`); never `loading="lazy"`
  the hero.
- Serve responsive, modern-format (WebP/AVIF), correctly sized images.
- Defer or `async` non-critical JS; inline critical CSS; remove render-blocking resources.
- `preconnect` to the origin serving the LCP asset.

## INP — Interaction to Next Paint (interactivity)

Responsiveness across the whole visit — the worst (near-worst) delay between a user
interaction and the next visual update. Bands: good ≤ 200ms, poor > 500ms.

**Common causes**

- Long JavaScript tasks blocking the main thread (heavy event handlers, large reducers,
  synchronous work on click/input).
- Expensive React/framework re-renders or un-memoized work on interaction.
- A very large DOM making layout/style recalculation slow on every update.
- Heavy hydration on first interaction (especially CSR-heavy SPAs).
- Third-party scripts contending for the main thread.

**Remediations**

- Break long tasks into chunks; yield to the main thread (`scheduler.yield()` /
  `setTimeout`); move heavy compute to a Web Worker.
- Debounce/throttle high-frequency handlers; memoize expensive renders; virtualize long
  lists.
- Reduce DOM size and CSS selector complexity.
- Defer/lazy-load non-critical third-party scripts; audit their main-thread cost.
- Show immediate visual feedback (optimistic UI) so the next paint isn't gated on the work.

## CLS — Cumulative Layout Shift (visual stability)

How much visible content shifts unexpectedly during the visit. Unitless score; bands:
good ≤ 0.1, poor > 0.25.

**Common causes**

- Images / video / iframes without explicit `width`/`height` (or `aspect-ratio`), so the
  page reflows when they load.
- Ads, embeds, or banners injected without reserved space.
- Web fonts swapping (FOIT/FOUT) and re-flowing text.
- Content inserted above existing content (cookie banners, "new content" prompts).
- Actions waiting on a network response that then shift layout.

**Remediations**

- Always set dimensions or `aspect-ratio` on media; reserve space for ad/embed slots.
- `font-display: optional`/`swap` plus preloading fonts to minimize swap reflow.
- Never insert content above existing content unless in response to a user interaction.
- Use `transform` animations (compositor-only) rather than ones that change layout.
- Reserve skeleton space for async-loaded modules.

## FCP — First Contentful Paint (early paint)

Time until the first text or image paints — the precursor to LCP. Bands: good ≤ 1800ms,
poor > 3000ms. A poor FCP usually drags LCP with it; fix FCP first.

**Common causes**

- Slow TTFB (same root as LCP — the document is late).
- Render-blocking CSS/JS in the critical path.
- Slow font loading blocking text paint.
- Heavy client-side bootstrapping before anything renders.

**Remediations**

- Reduce TTFB (edge cache, faster origin, SSR).
- Eliminate render-blocking resources; inline critical CSS; defer the rest.
- `preconnect`/`dns-prefetch` to critical third-party origins.
- Ship less critical-path JS; prefer server-rendered first paint over CSR.

## A note on percentiles

The bands are defined for **p75** (the Core Web Vitals field standard) — anchor findings
there. The product UI defaults to **p90**, and p99 is the tail. If p90/p99 is poor while
p75 is good, that's a slow-tail story (a subset of slow sessions), not a page-wide
regression — worth a `pattern:` note, rarely a standalone finding.
