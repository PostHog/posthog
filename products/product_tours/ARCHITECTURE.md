# Product Tours Architecture

Product tours allow PostHog users to implement automated onboarding and product walkthroughs, similar to tools like Userpilot and Product Fruits.

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PostHog Main Repo                                  │
│  ┌──────────────────────────────────┐   ┌─────────────────────────────────┐ │
│  │        Toolbar (Authoring)       │   │      Backend (Storage)          │ │
│  │  frontend/src/toolbar/           │   │  products/product_tours/backend │ │
│  │  product-tours/                  │   │                                 │ │
│  │                                  │   │  - Django models                │ │
│  │  - Element inspector             │   │  - REST API                     │ │
│  │  - Step editor with rich text    │   │  - Feature flag management      │ │
│  │  - Tour builder UI               │   │  - Public SDK endpoint          │ │
│  └────────────┬─────────────────────┘   └──────────────┬──────────────────┘ │
│               │ creates/edits via API                  │                     │
│               └────────────────────────────────────────┤                     │
│                                                        │ serves tours        │
└────────────────────────────────────────────────────────┼─────────────────────┘
                                                         │
                                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        posthog-js SDK (Display)                              │
│              packages/browser/src/extensions/product-tours/                  │
│                                                                              │
│  - Fetches active tours from /api/product_tours                             │
│  - Evaluates eligibility (URL, selector, device, flags)                     │
│  - Renders tooltip UI with spotlight                                        │
│  - Captures analytics events                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```text
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐     ┌───────────────┐
│   Toolbar    │────▶│ Backend API   │────▶│ Database + Flag  │────▶│ SDK Polling   │
│   (create)   │     │ (CRUD)        │     │ (stored)         │     │ (display)     │
└──────────────┘     └───────────────┘     └──────────────────┘     └───────────────┘
                                                                            │
                                                                            ▼
                                                                    ┌───────────────┐
                                                                    │ End User Sees │
                                                                    │ Tour Tooltip  │
                                                                    └───────────────┘
```

## Layer 1: Backend (Storage & API)

**Location:** `products/product_tours/backend/`

### Key Files

| File                  | Purpose                            |
| --------------------- | ---------------------------------- |
| `models.py`           | `ProductTour` Django model         |
| `api/product_tour.py` | CRUD ViewSet + public SDK endpoint |

### Data Model

| Field                     | Type            | Description                                      |
| ------------------------- | --------------- | ------------------------------------------------ |
| `id`                      | UUID            | Primary key                                      |
| `team`                    | FK(Team)        | Owner team                                       |
| `name`                    | string          | Tour name (unique per team when not archived)    |
| `description`             | string          | Optional description                             |
| `internal_targeting_flag` | FK(FeatureFlag) | Auto-created flag for targeting                  |
| `content`                 | JSON            | Steps, appearance, conditions (see schema below) |
| `start_date`              | datetime        | When tour becomes active                         |
| `end_date`                | datetime        | When tour stops                                  |
| `archived`                | bool            | Soft delete flag                                 |

### Content JSON Schema

```json
{
  "steps": [
    {
      "selector": "#my-button",
      "content": { "type": "doc", "content": [...] }  // TipTap JSON format
    }
  ],
  "appearance": {
    "backgroundColor": "#ffffff",
    "textColor": "#1d1d1f",
    "buttonColor": "#1d4aff",
    "buttonTextColor": "#ffffff",
    "borderRadius": 8,
    "borderColor": "#e5e5e5",
    "whiteLabel": false
  },
  "conditions": {
    "url": "/dashboard",
    "urlMatchType": "contains",  // exact | contains | regex
    "selector": "#target-element",
    "deviceTypes": ["desktop", "mobile"]
  }
}
```

### API Endpoints

| Method | Path                                     | Description                          |
| ------ | ---------------------------------------- | ------------------------------------ |
| GET    | `/api/projects/{id}/product_tours/`      | List tours (authenticated)           |
| POST   | `/api/projects/{id}/product_tours/`      | Create tour                          |
| GET    | `/api/projects/{id}/product_tours/{id}/` | Get tour                             |
| PATCH  | `/api/projects/{id}/product_tours/{id}/` | Update tour                          |
| DELETE | `/api/projects/{id}/product_tours/{id}/` | Archive tour (soft delete)           |
| GET    | `/api/product_tours`                     | Public endpoint for SDK (token auth) |

### Internal Feature Flag

Each tour gets an auto-created feature flag:

- Key format: `product-tour-targeting-{slugified_name}-{random_id}`
- Filters out users with person properties: `$product_tour_completed/{tour_id}` or `$product_tour_dismissed/{tour_id}`
- Active when `start_date` is set and tour is not archived

---

## Layer 2: Toolbar (Authoring UI)

**Location:** `frontend/src/toolbar/product-tours/`

The toolbar is injected into the customer's website to allow visual tour creation.

### Key Files

| File                          | Purpose                                                     |
| ----------------------------- | ----------------------------------------------------------- |
| `productToursLogic.ts`        | Kea logic for tour state, element inspection, form handling |
| `ProductToursToolbarMenu.tsx` | Sidebar menu listing tours + "Create new" button            |
| `ProductToursEditingBar.tsx`  | Bottom bar for editing tour name, steps, save/cancel        |
| `StepEditor.tsx`              | Popup editor for step content + CSS selector                |
| `ElementHighlight.tsx`        | Visual highlight overlay for hovered/selected elements      |
| `ToolbarRichTextEditor.tsx`   | TipTap-based rich text editor for step content              |
| `NewTourModal.tsx`            | Initial modal when creating a new tour                      |

### Workflow

1. User opens toolbar → clicks "Product tours" menu
2. Creates new tour or selects existing
3. Enters inspection mode → hovers over page elements
4. Clicks element → StepEditor appears with auto-generated selector
5. Writes step content (title, description) using rich text editor
6. Adds more steps or saves tour
7. Tour saved via `POST /api/projects/@current/product_tours/`

### Element Selector Generation

Uses `elementToActionStep()` from toolbar utils to generate CSS selectors from clicked elements, considering:

- Element ID, classes, attributes
- Custom data attributes configured in project settings
- Nth-child for disambiguation

---

## Layer 3: SDK (Display Runtime)

**Location (external repo):** `posthog-js/packages/browser/src/extensions/product-tours/`

The SDK fetches and displays tours to end-users on the customer's website.

### Key Files

| File                                | Purpose                                           |
| ----------------------------------- | ------------------------------------------------- |
| `product-tours.tsx`                 | `ProductTourManager` class - main orchestrator    |
| `product-tours-utils.ts`            | Eligibility checks, positioning, TipTap rendering |
| `product-tour.css`                  | Styles for tooltip, spotlight, animations         |
| `components/ProductTourTooltip.tsx` | Preact component for tour UI                      |

### ProductTourManager Lifecycle

```text
start() → setInterval(1s) → evaluateAndDisplayTours()
                                    │
                                    ▼
                          getActiveProductTours()
                                    │
                                    ▼
                          for each tour: isTourEligible()?
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                        Yes                  No
                          │                   │
                          ▼                   └──▶ skip
                    showTour()
                          │
                          ▼
                renderCurrentStep()
                          │
                          ▼
                ProductTourTooltip (Preact)
```

### Eligibility Checks (`isTourEligible`)

1. **Date range:** `start_date ≤ now ≤ end_date`
2. **URL match:** Current URL matches `conditions.url` (exact/contains/regex)
3. **Selector match:** `conditions.selector` exists in DOM
4. **Device type:** Current device matches `conditions.deviceTypes`
5. **Feature flag:** `internal_targeting_flag_key` evaluates true
6. **Not completed/dismissed:** Check localStorage keys `ph_product_tour_completed_{id}` / `ph_product_tour_dismissed_{id}`

### Rendering

- Uses **Shadow DOM** for style isolation
- **Preact** for lightweight reactive UI
- **Spotlight:** Dark overlay with cutout around target element
- **Tooltip:** Positioned relative to element (right → left → bottom → top preference)
- **Smooth scroll:** Auto-scrolls target into view before showing

### Events Captured

| Event                               | Description       | Key Properties                                                                       |
| ----------------------------------- | ----------------- | ------------------------------------------------------------------------------------ |
| `product tour shown`                | Tour displayed    | `$product_tour_id`, `$product_tour_name`, `$product_tour_render_reason`              |
| `product tour step shown`           | Step rendered     | `$product_tour_step_id`, `$product_tour_step_order`, `$product_tour_step_selector`   |
| `product tour step completed`       | User clicked Next | `$product_tour_step_id`, `$product_tour_step_order`                                  |
| `product tour dismissed`            | User dismissed    | `$product_tour_dismiss_reason` (user_clicked_skip, escape_key, user_clicked_outside) |
| `product tour completed`            | All steps done    | `$product_tour_steps_count`                                                          |
| `product tour step selector failed` | Selector issue    | `$product_tour_error` (not_found, not_visible, multiple_matches)                     |

### Person Properties Set

On tour completion:

```javascript
posthog.capture('$set', {
  $set: { [`$product_tour_completed/${tour_id}`]: true },
})
```

### Public SDK API

Exposed via `posthog.productTours`:

```javascript
// Manually show a tour (bypasses eligibility checks, clears localStorage state)
posthog.productTours.showProductTour('tour-uuid')

// Control active tour
posthog.productTours.dismissProductTour()
posthog.productTours.nextStep()
posthog.productTours.previousStep()

// Fetch tours
posthog.productTours.getProductTours((tours) => console.log(tours))
posthog.productTours.getActiveProductTours((tours) => console.log(tours))

// Reset state (useful for testing)
posthog.productTours.resetTour('tour-uuid') // Clear completed/dismissed for one tour
posthog.productTours.resetAllTours() // Clear all completed/dismissed state
posthog.productTours.clearCache() // Clear cached tour data
```

---

## Layer 4: PostHog App UI (TODO)

**Status:** Not yet implemented

Will provide a dedicated UI for viewing, managing, and analyzing product tours within the PostHog app (outside the toolbar).

**Planned location:** `frontend/src/scenes/product-tours/`

**Planned features:**

- List all tours with status (draft, active, completed)
- View tour analytics (completion rate, drop-off by step)
- Edit tour content without launching toolbar
- Clone/duplicate tours
- Preview tours

---

## Cross-Cutting Concerns

### Authentication

| Context               | Auth Method                                      |
| --------------------- | ------------------------------------------------ |
| Toolbar → Backend API | Temporary token (`TemporaryTokenAuthentication`) |
| SDK → Public endpoint | Project API key in request                       |
| App UI → Backend API  | Session auth (standard PostHog auth)             |

### Error Handling

- **Selector not found:** SDK skips step, logs event, continues to next step
- **Multiple selector matches:** SDK uses first match, logs warning
- **Element not visible:** SDK skips step, continues
- **API errors:** Toolbar shows toast notification

---

## Known Gaps / TODOs

- **App UI not implemented** - no way to view/manage tours in PostHog app yet (only toolbar)
- **Conditions UI missing** - URL/device matching not exposed in toolbar yet
- **Appearance customization** - not wired up in toolbar UI
- **Step reordering** - can't drag to reorder steps in toolbar

---

## Future Enhancements (v2)

- **User-provided targeting flag** (`linked_flag`) - use existing feature flag instead of auto-created
- **AI-powered tour generation** - generate tours from page analysis without manual element selection
- **Response sampling** - show tour to percentage of eligible users
- **Recurring tours** - show tour again after time period
- **Tour analytics dashboard** - dedicated insights for tour performance
- **Caching layer** - cache tours for faster SDK delivery
- **A/B testing** - test different tour variants

---

## Development Workflow

### Adding a new field to tours

1. Add field to `ProductTour` model in `models.py`
2. Create migration: `python manage.py makemigrations product_tours`
3. Add to serializers in `api/product_tour.py`
4. Update toolbar form in `productToursLogic.ts`
5. Update SDK types in `posthog-product-tours-types.ts`
6. Handle field in SDK display logic

### Testing the toolbar locally

The toolbar requires a specific setup because it runs inside an iframe on the customer's site:

1. **Start PostHog:** `hogli start`
2. **Build frontend:** `cd frontend && pnpm build` (repeat after every change)
3. **Enable feature flag:** Add your local account email to the `product-tours` feature flag
   - ⚠️ The toolbar fetches feature flags from **prod**, not local - your email must be in the prod flag
4. **Run test site:** Start the Next.js playground (`pnpm dev` in playground repo)
5. **Configure authorized URLs:**
   - Go to toolbar page in local PostHog (e.g., `http://localhost:8010/project/1/toolbar`)
   - Add playground URL to authorized URLs (e.g., `https://localhost:3000`)
6. **Inject toolbar:**
   - Click "Launch" dropdown → "Copy launch code"
   - Paste the code in playground browser console
7. **Create/test tours** via the toolbar UI

### Testing SDK display

1. Create a tour via toolbar with `start_date` set
2. Verify tour appears in `/api/product_tours` response
3. Open a fresh browser/incognito (to clear localStorage)
4. Navigate to page matching tour conditions
5. Tour should appear within 1 second (SDK polling interval)

### Clearing remote config cache

If you change `remote_config.py` and don't see updates at `/array/{token}/config.js`:

```python
# In Django shell
from django.core.cache import cache
from posthog.models.remote_config import RemoteConfig, cache_key_for_team_token
from posthog.models.team import Team

token = 'your-token-here'
cache.delete(cache_key_for_team_token(token))

team = Team.objects.get(api_token=token)
rc, _ = RemoteConfig.objects.get_or_create(team=team)
rc.sync(force=True)
```
