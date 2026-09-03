# Reusable notebook widgets

## Product narrative

Reusable widgets turn a useful generated notebook visualization into a shared, versioned building block.

A notebook editor opens a generated widget's menu and selects **Convert to reusable widget**. A publishing flow then:

- proposes a name, description, and searchable metadata;
- generalizes notebook-specific inputs into a stable semantic contract;
- creates an instance binding that maps the original notebook values back into that contract;
- optionally uses an AI-assisted cleanup pass to remove notebook-specific assumptions;
- previews the generalized widget before publishing;
- saves bounded, safe demo inputs for catalog previews; and
- publishes the first shared version only after the editor confirms it.

The notebooks index has **Notebooks** and **Widgets** tabs. The widget catalog supports search and opens a dedicated widget page with a live demo, input contract, usage, consumers, editing, and immutable version history.

Notebook instances reference a stable reusable widget. Unpinned instances follow its latest published version. An instance can instead pin an immutable version. Selecting an older version in the notebook offers **Pin this version**, while pinned instances offer **Use latest**.

Editing a reusable instance is deliberate. The notebook UI and notebook agent offer two choices:

- open the reusable widget and publish a shared update; or
- fork it into a notebook-local widget and change only that copy.

When the notebook agent needs a visualization, it can search the catalog using the user's goal, available dataframes, dataframe schemas, and widget metadata. It suggests matching widgets and their proposed bindings before inserting one. Regeneration and forking remain available when no catalog result is a good fit.

## Input contracts and instance bindings

A reusable widget owns semantic input slots. Each notebook placement owns a binding that maps local values to those slots. Local dataframe names, argument ordering, column names, filters, and derived values therefore do not leak into the shared contract.

For example, a widget contract might expect `primary`, `comparison`, `categoryColumn`, and `valueColumn`. Two instances can bind `sales` and `forecast` in one placement, then `current_users` and `previous_users` in another. Either placement can reverse inputs or reshape columns without editing the reusable implementation.

The initial adapter-language candidate is a constrained, pure Hog expression executed by the browser VM. The binding receives a capability-limited notebook environment and returns an object validated against the selected widget version's schema. It must not perform network requests, capture events, mutate notebook state, or invoke arbitrary notebook operations.

The same representation should remain portable to static JavaScript for exported HTML when Hog compilation supports the required expression subset.

```text
Notebook values
      |
      v
Instance binding (pure Hog expression)
      |
      v
Contract validation
      |
      v
Canonical widget inputs
      |
      v
Reusable widget artifact
```

Bindings must expose their dataframe dependencies so notebook execution and staleness tracking remain reactive. Large dataframes should remain references or lazy views where possible instead of being copied into notebook content or API payloads.

An unpinned instance always advances to the newest version. Direct bindings keep schema-hash enforcement, while Hog mappings validate their tabular output against the version's required columns. A contract mismatch produces an actionable error so the placement can be remapped or pinned to an earlier version.

## Existing foundations on `master`

- `GeneratedWidget` provides a stable team-scoped identity backed by a Canvas artifact.
- `GeneratedWidgetVersion` stores immutable generated versions, input contracts, prompts, security reviews, and Canvas source versions.
- `NotebookWidgetInstance` connects a notebook node to a widget and already has `pinned_version`.
- Widget APIs already expose generation, status, history, source, revert, and bounded dataframe reads.
- The frontend already renders generated widget artifacts, browses version history, regenerates, improves, and refreshes data.
- The static widget catalog describes built-in generation capabilities, but it is not yet a user-published widget catalog.

The implementation should extend these primitives rather than introduce a parallel widget runtime.

## Implemented foundation

- [x] Project-scoped publication metadata and immutable per-version demo fixtures.
- [x] Catalog list and detail APIs, live demo rendering, and generated clients.
- [x] Notebook index tabs, searchable catalog UI, and reusable widget detail scene.
- [x] Convert action in the widget menu with explicit demo-data disclosure.
- [x] Stable `<Widget id=... version=... inputs=... />` serialization.
- [x] Follow-latest behavior, immutable version pinning, and notebook-local forking.
- [x] Shared edits from the catalog page and rejection of accidental notebook-local shared edits.
- [x] Per-placement input bindings with optional bounded browser Hog transformations.
- [x] MCP search, detail, and attach operations for agent discovery and insertion.
- [x] Focused backend, frontend logic, component, and Hog VM tests.

The unchecked items below remain the hardening and expansion backlog rather than prerequisites for the implemented first release.

## Decisions to validate

- [ ] Confirm that `GeneratedWidget` is the correct reusable identity rather than a notebook-local generation aggregate.
- [ ] Define draft, published, deprecated, and unavailable lifecycle states.
- [ ] Define project/team ownership, organization sharing, and future public sharing boundaries.
- [ ] Decide whether the first release is team-scoped only.
- [ ] Define author and editor permissions for metadata changes and new versions.
- [ ] Define stable widget IDs for notebook markup and API URLs.
- [ ] Define semantic contract schema, compatibility rules, defaults, and validation errors.
- [x] Make an unpinned instance intentionally dynamic; pin it when a notebook needs reproducible rendering.
- [ ] Define fork versus detach behavior and whether lineage is visible.
- [ ] Define deprecation and deletion rules. Published versions should be immutable and should not be hard-deleted while referenced.
- [ ] Define demo-data provenance, redaction, row and byte limits, and retention.
- [ ] Decide whether demo data is an immutable version field or a separately replaceable preview fixture.

## Implementation plan

### 1. Architecture spike

- [ ] Trace generated-widget creation, version publication, Canvas builds, frame reads, notebook saving, and agent mutation paths.
- [ ] Inspect the browser Hog VM and static-JavaScript compiler capabilities.
- [ ] Prototype a pure binding expression over two differently named dataframe references.
- [ ] Prove dependency extraction for direct references and supported transformations.
- [ ] Measure row projection, filtering, renaming, and derived-value behavior over representative dataframe sizes.
- [ ] Decide whether bindings produce dataframe references, lazy views, or bounded materialized values.
- [ ] Document the supported binding-expression subset and failure behavior.

### 2. Persistence and domain lifecycle

- [ ] Add publication metadata to the reusable widget identity: description, lifecycle status, visibility, timestamps, and editor attribution as required.
- [ ] Add immutable version metadata: semantic input schema, compatibility version, and demo inputs or demo-data reference.
- [x] Add instance metadata for input bindings; represent follow-latest with a null pinned version.
- [ ] Keep all tenant data team-scoped and use fail-closed managers.
- [ ] Add domain functions for publish, update metadata, publish version, pin, unpin, fork, resolve version, and validate binding compatibility.
- [ ] Keep related writes in narrow transactions and schedule artifact work after commit.
- [ ] Add additive, deployment-safe Django migrations.

### 3. Typed API surface

- [ ] Add team-scoped catalog list and detail endpoints under the notebooks product routes.
- [ ] Add typed publish, metadata update, pin, unpin, fork, and compatibility-check actions.
- [ ] Add typed serializers with field descriptions and explicit request and response schemas.
- [ ] Apply notebook, query, and widget ownership permissions consistently.
- [ ] Regenerate product OpenAPI clients and consume generated `*Api` types in the frontend.

### 4. Convert-to-reusable flow

- [ ] Add **Convert to reusable widget** to the generated widget's existing action menu.
- [ ] Build a review flow for metadata, proposed semantic inputs, generated binding, demo inputs, and live preview.
- [ ] Preserve the original appearance by replacing notebook-specific access with the generated original-instance binding.
- [ ] Make AI cleanup optional, reviewable, cancelable, and incapable of publishing silently.
- [ ] Surface assumptions that could not be generalized safely.
- [ ] Publish version 1 and convert the source node into an unpinned reusable instance after confirmation.

### 5. Widget catalog and detail scene

- [ ] Add **Notebooks** and **Widgets** tabs to the notebooks index while preserving existing notebook actions and filters.
- [ ] Add loading, error, empty, and populated catalog states using existing Lemon components.
- [ ] Search by name, description, tags, semantic inputs, and available structured metadata.
- [ ] Add a widget detail scene with live demo, editable demo inputs, contract, usage, consumers, version history, and shared-edit actions.
- [ ] Ensure catalog and detail layouts work in a narrow main-content container.
- [ ] Add focused Storybook coverage for new presentational states.

### 6. Reusable instances and version behavior

- [ ] Extend `<Widget />` notebook markup with stable widget identity, binding, and optional immutable version.
- [x] Resolve unpinned instances to the latest published version.
- [x] Report direct-binding schema mismatches and transformed-output contract mismatches explicitly.
- [ ] Show the rendered version, update availability, binding errors, and publication status.
- [ ] Replace the existing restore-only version action with **Pin this version** where appropriate.
- [ ] Add **Use latest**, **Open widget**, **Edit binding**, and **Fork for this notebook** actions.
- [ ] Keep version-specific artifact URLs, source inspection, and security review intact.
- [ ] Define export behavior so bindings and artifacts remain functional in exported HTML.

### 7. Shared-edit safeguards

- [ ] Detect reusable references in direct UI edits and notebook-agent mutation requests.
- [ ] Route shared implementation changes to the widget detail scene.
- [ ] Explain the affected unpinned consumers before publication.
- [ ] Offer an explicit fork for notebook-local changes.
- [ ] Prevent a notebook-local regeneration action from silently changing a shared widget.

### 8. Agent discovery and input rewriting

- [ ] Add a catalog search operation for notebook agents.
- [ ] Rank results by prompt meaning, widget metadata, semantic contract, dataframe columns, and data types.
- [ ] Let the agent inspect a candidate contract and demo before insertion.
- [ ] Generate a proposed Hog binding from available notebook dataframes.
- [ ] Explain non-obvious mappings such as reversed series or renamed columns.
- [ ] Validate the binding before insertion and report actionable mismatches.
- [ ] Fall back to generating a notebook-local widget when no result fits.
- [ ] Suggest publishing newly generated widgets after they prove useful.

### 9. Safety, observability, and rollout

- [ ] Enforce bounded binding evaluation and demo-data sizes.
- [ ] Keep widget artifacts sandboxed and preserve existing security-review gates.
- [ ] Prevent demo fixtures from exposing customer data or credentials.
- [ ] Add audit activity for publication, new versions, metadata changes, pinning, and deprecation if these events belong in notebook activity.
- [ ] Add product analytics for conversion, insertion, binding failures, pinning, forking, and catalog search outcomes.
- [ ] Gate the feature for incremental rollout and provide useful failure states when prerequisites are unavailable.
- [ ] Update user-facing notebook documentation in the same change set that ships behavior.

## Intended delivery slices

- [ ] **Slice 1:** team-scoped publication metadata, catalog API, index tab, catalog list, and a read-only detail page using existing widget artifacts.
- [ ] **Slice 2:** insert an existing reusable widget, explicit per-instance dataframe bindings, unpinned resolution, pinning, and forking.
- [ ] **Slice 3:** conversion assistant, semantic-contract extraction, optional AI cleanup, and demo-data capture.
- [ ] **Slice 4:** shared editing, compatibility-aware publication, consumer safeguards, and assisted binding migration.
- [ ] **Slice 5:** agent search, ranking, binding generation, and recommendation.
- [ ] **Slice 6:** static export support, richer visibility controls, observability, docs, and rollout hardening.

## Test strategy

- [x] Extend backend widget tests with observable lifecycle cases for team isolation, publication, latest resolution, pinning, and fork behavior.
- [ ] Test contract and binding compatibility as pure functions where possible.
- [ ] Extend kea logic tests for catalog resolution states and instance actions.
- [ ] Add small DOM tests only for interactions that cannot be verified through logic.
- [ ] Test Hog binding evaluation and dependency extraction with renamed, reversed, transformed, missing, and incompatible inputs.
- [ ] Preserve artifact bridge tests for version-specific and bounded frame reads.
- [ ] Run scoped tests during development, then frontend fix, frontend typecheck, migration checks, and CI preflight once the first slice is complete.

## Initial success criteria

- [ ] An editor can publish an existing generated widget to a team-scoped catalog.
- [ ] The widgets tab lists published widgets and opens a live read-only detail page.
- [ ] A notebook can contain two instances of the same widget bound to different dataframe names.
- [x] An unpinned instance follows the newest published version.
- [ ] A pinned instance remains on its selected immutable version.
- [ ] Shared edits and notebook-local forks are clearly distinct.
- [ ] The notebook agent can discover a relevant saved widget and propose a valid binding before inserting it.
