import type { JourneyRunApi, JourneyRunDetailApi, JourneyRunStepApi, JourneyStepApi } from '../generated/api.schemas'

/** Invented run data for stories. The screenshots are SVGs drawn here, so no image files ship with the stories. */

const WIDTH = 1280
const HEIGHT = 800

function toDataUri(svg: string): string {
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

interface PageOptions {
    navItems: string[]
    /** False draws the header as a narrow container that cuts off everything past the nav, sign up included. */
    signUpVisible: boolean
    heading: string
}

function sitePage({ navItems, signUpVisible, heading }: PageOptions): string {
    const nav = navItems
        .map((item, index) => `<text x="${250 + index * 120}" y="52" font-size="20" fill="#334155">${item}</text>`)
        .join('')
    const signUp = signUpVisible
        ? `<rect x="1090" y="22" width="150" height="46" rx="8" fill="#1d4ed8"/>
           <text x="1165" y="52" font-size="20" fill="#ffffff" text-anchor="middle" font-weight="600">Sign up</text>`
        : ''
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}" font-family="Arial, sans-serif">
  <rect width="${WIDTH}" height="${HEIGHT}" fill="#f8fafc"/>
  <rect width="${WIDTH}" height="90" fill="#ffffff"/>
  <line x1="0" y1="90" x2="${WIDTH}" y2="90" stroke="#e2e8f0" stroke-width="2"/>
  <rect x="40" y="26" width="38" height="38" rx="8" fill="#0f172a"/>
  <text x="92" y="54" font-size="24" font-weight="700" fill="#0f172a">Example</text>
  <svg x="0" y="0" width="${signUpVisible ? WIDTH : 1060}" height="90">${nav}</svg>
  ${signUp}
  <text x="640" y="250" font-size="52" font-weight="700" fill="#0f172a" text-anchor="middle">${heading}</text>
  <text x="640" y="305" font-size="24" fill="#475569" text-anchor="middle">Pick the plan that fits your team. Change it any time.</text>
  ${[0, 1, 2]
      .map(
          (
              column
          ) => `<rect x="${130 + column * 350}" y="380" width="320" height="330" rx="14" fill="#ffffff" stroke="#e2e8f0" stroke-width="2"/>
  <text x="${290 + column * 350}" y="440" font-size="26" font-weight="700" fill="#0f172a" text-anchor="middle">${['Starter', 'Team', 'Enterprise'][column]}</text>
  <text x="${290 + column * 350}" y="500" font-size="40" font-weight="700" fill="#1d4ed8" text-anchor="middle">${['$0', '$49', 'Custom'][column]}</text>
  <rect x="${170 + column * 350}" y="620" width="240" height="50" rx="8" fill="#e2e8f0"/>`
      )
      .join('')}
</svg>`
}

function diffImage(boxes: { x: number; y: number; width: number; height: number }[]): string {
    return toDataUri(`<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}">
  <rect width="${WIDTH}" height="${HEIGHT}" fill="#9ca3af" opacity="0.35"/>
  ${boxes.map((box) => `<rect x="${box.x}" y="${box.y}" width="${box.width}" height="${box.height}" fill="#ef4444" opacity="0.85"/>`).join('')}
</svg>`)
}

const BASE_NAV = ['Product', 'Pricing', 'Docs', 'Blog', 'Customers', 'Careers']
const WIDER_NAV = [...BASE_NAV, 'Changelog']

export const BASELINE_SCREENSHOT = toDataUri(
    sitePage({ navItems: BASE_NAV, signUpVisible: true, heading: 'Simple pricing for every team' })
)
export const CLIPPED_SCREENSHOT = toDataUri(
    sitePage({ navItems: WIDER_NAV, signUpVisible: false, heading: 'Simple pricing for every team' })
)
const NEW_HEADING_SCREENSHOT = toDataUri(
    sitePage({ navItems: BASE_NAV, signUpVisible: true, heading: 'Pricing that grows with you' })
)
const CLIPPED_DIFF = diffImage([
    { x: 970, y: 30, width: 110, height: 30 },
    { x: 1090, y: 22, width: 150, height: 46 },
])
const HEADING_DIFF = diffImage([{ x: 300, y: 205, width: 680, height: 60 }])

export const RUN_JOURNEY_ID = '0193f1a2-0000-7000-8000-000000000001'

export const RUN_JOURNEY_STEPS: JourneyStepApi[] = [
    { type: 'pageview', url: 'https://example.com/pricing', url_matching: 'exact' },
    {
        type: 'element_click',
        selector: 'header a.signup',
        text: 'Sign up',
        href: '/signup',
        url: 'https://example.com/pricing',
        url_matching: 'exact',
    },
    { type: 'pageview', url: '/signup', url_matching: 'contains' },
    {
        type: 'element_click',
        selector: 'form#signup button[type="submit"]',
        text: 'Create account',
        href: null,
        url: null,
        url_matching: 'exact',
    },
]

function runStep(index: number, changes: Partial<JourneyRunStepApi>): JourneyRunStepApi {
    return {
        index,
        step: RUN_JOURNEY_STEPS[index],
        status: 'passed',
        failure_reason: null,
        message: '',
        screenshot_url: BASELINE_SCREENSHOT,
        baseline_screenshot_url: BASELINE_SCREENSHOT,
        diff_screenshot_url: null,
        diff_percentage: 0,
        visual_change: 'unchanged',
        duration_ms: 640,
        ...changes,
    }
}

function journeyRun(id: string, changes: Partial<JourneyRunApi>): JourneyRunApi {
    return {
        id,
        team_id: 997,
        journey_id: RUN_JOURNEY_ID,
        trigger: 'manual',
        status: 'passed',
        start_url: 'https://example.com/pricing',
        base_url: null,
        commit_sha: null,
        branch: null,
        viewport_width: WIDTH,
        viewport_height: HEIGHT,
        error: null,
        baseline_run_id: null,
        created_by_id: 1,
        created_at: '2026-11-19T09:00:00Z',
        started_at: '2026-11-19T09:00:02Z',
        finished_at: '2026-11-19T09:00:36Z',
        deploy_id: null,
        failed_step_index: null,
        failure_reason: null,
        ...changes,
    }
}

export const RUNNING_RUN = journeyRun('0193f1b0-0000-7000-8000-000000000005', {
    trigger: 'deploy',
    status: 'running',
    start_url: 'https://preview-1432.example.com/pricing',
    base_url: 'https://preview-1432.example.com',
    commit_sha: '9c41be07d2f8a5e6b3c1d0e9f8a7b6c5d4e3f2a1',
    branch: 'update-pricing-copy',
    created_at: '2026-11-19T23:58:10Z',
    started_at: '2026-11-19T23:58:12Z',
    finished_at: null,
})

export const FAILED_RUN = journeyRun('0193f1b0-0000-7000-8000-000000000004', {
    trigger: 'deploy',
    status: 'failed',
    commit_sha: '4f2a9c1de8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3',
    branch: 'add-changelog-nav-item',
    baseline_run_id: '0193f1b0-0000-7000-8000-000000000002',
    failed_step_index: 1,
    failure_reason: 'element_not_visible',
    created_at: '2026-11-19T16:20:00Z',
    started_at: '2026-11-19T16:20:03Z',
    finished_at: '2026-11-19T16:20:24Z',
})

export const PASSED_WITH_CHANGE_RUN = journeyRun('0193f1b0-0000-7000-8000-000000000003', {
    baseline_run_id: '0193f1b0-0000-7000-8000-000000000002',
    created_at: '2026-11-19T11:05:00Z',
    started_at: '2026-11-19T11:05:02Z',
    finished_at: '2026-11-19T11:05:41Z',
})

const ERRORED_RUN = journeyRun('0193f1b0-0000-7000-8000-000000000002', {
    status: 'errored',
    start_url: null,
    error: "The run can't open its start page. staging.example.net isn't one of this project's authorized URLs. Add it to the authorized URLs in project settings, then try again.",
    base_url: 'https://staging.example.net',
    created_at: '2026-11-18T15:40:00Z',
    started_at: '2026-11-18T15:40:01Z',
    finished_at: '2026-11-18T15:40:02Z',
})

const FIRST_RUN = journeyRun('0193f1b0-0000-7000-8000-000000000001', {
    created_at: '2026-11-17T10:00:00Z',
    started_at: '2026-11-17T10:00:02Z',
    finished_at: '2026-11-17T10:00:44Z',
})

export const RUNS_PAGE = {
    count: 5,
    results: [RUNNING_RUN, FAILED_RUN, PASSED_WITH_CHANGE_RUN, ERRORED_RUN, FIRST_RUN],
}

export const FAILED_RUN_DETAIL: JourneyRunDetailApi = {
    ...FAILED_RUN,
    steps: [
        runStep(0, {
            screenshot_url: CLIPPED_SCREENSHOT,
            diff_screenshot_url: CLIPPED_DIFF,
            diff_percentage: 1.27,
            visual_change: 'changed',
            duration_ms: 1840,
        }),
        runStep(1, {
            status: 'failed',
            failure_reason: 'element_not_visible',
            message:
                'The element is in the page, but a container that hides its overflow cuts it off, so no part of it is visible.',
            screenshot_url: CLIPPED_SCREENSHOT,
            diff_screenshot_url: CLIPPED_DIFF,
            diff_percentage: 1.27,
            visual_change: 'changed',
            duration_ms: 5020,
        }),
        runStep(2, {
            status: 'skipped',
            message: 'Skipped because an earlier step failed.',
            screenshot_url: null,
            baseline_screenshot_url: null,
            diff_percentage: null,
            visual_change: null,
            duration_ms: null,
        }),
        runStep(3, {
            status: 'skipped',
            message: 'Skipped because an earlier step failed.',
            screenshot_url: null,
            baseline_screenshot_url: null,
            diff_percentage: null,
            visual_change: null,
            duration_ms: null,
        }),
    ],
}

export const PASSED_WITH_CHANGE_RUN_DETAIL: JourneyRunDetailApi = {
    ...PASSED_WITH_CHANGE_RUN,
    steps: [
        runStep(0, {
            screenshot_url: NEW_HEADING_SCREENSHOT,
            diff_screenshot_url: HEADING_DIFF,
            diff_percentage: 3.48,
            visual_change: 'changed',
            duration_ms: 1710,
        }),
        runStep(1, { screenshot_url: NEW_HEADING_SCREENSHOT, diff_percentage: 0, duration_ms: 820 }),
        runStep(2, { duration_ms: 1320 }),
        runStep(3, { visual_change: 'new', baseline_screenshot_url: null, diff_percentage: null, duration_ms: 690 }),
    ],
}

export const RUNNING_RUN_DETAIL: JourneyRunDetailApi = { ...RUNNING_RUN, steps: [] }
