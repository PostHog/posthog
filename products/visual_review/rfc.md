# Modular Architecture & Bazel Integration Plan

## Purpose

This document defines the future architectural direction for our Django monolith, focusing on:

* Introducing **Bazel** for selective testing (starting with a single app)
* Establishing a clear, Django-friendly **folder structure** for modular boundaries
* Using **dataclass-based DTOs** as internal module contracts
* Introducing **facades** as the only public API surface for modules
* Enforcing **isolation** between modules to avoid accidental cross-app leaks
* Providing guidance for developers unfamiliar with modern modular-monolith patterns

This is a forward-looking design document, not a migration guide.

---

# 1. Why Modularization?

As the codebase grows, running all tests for every change becomes expensive. Our goal:

* **Reduce CI time** via selective testing
* **Make module boundaries explicit**
* **Prevent accidental cross-app imports**
* **Preserve developer velocity as the system grows**

Bazel will eventually provide correctness guarantees that:

* Only tests affected by a change run
* Dependencies must be explicitly declared

To prepare for Bazel, we must introduce architectural boundaries inside the Django monolith.

---

# 2. Bazel (Initial Scope: Single App)

We will begin by Bazel-fying **one app** to:

* Validate the folder structure
* Test Bazel’s Python support
* Build the foundation for incremental test selection

Focus:

* One app = one Bazel target group
* Facade (`api/api.py`) will define the **public interface** Bazel recognizes
* Internal files will be private implementation details
* Presentation layer (DRF) will sit above the API but remain outside Bazel’s contract surface initially

Eventually this grows into:

* A target graph across apps
* True selective test execution

But this document is about foundational structure, not full rollout.

---

# 3. Folder Structure (Django-Friendly, Modular-Monolith Ready)

Each Django app adopts the following structure:

```text
myapp/
  backend/
    __init__.py
    apps.py
    models.py          # Django ORM only
    domain_types.py    # Enums / domain constants
    logic.py           # Business / domain logic
    BUILD.bazel        # Bazel targets: :contract, :impl, :presentation, :tasks

    tasks/
      __init__.py
      tasks.py         # Celery entrypoints (call facade)
      schedules.py     # Celery beat / periodic config (optional)

    api/
      __init__.py
      api.py           # Facade (public API for other backend modules)
      dtos.py          # DTOs used by facade

    presentation/
      __init__.py
      serializers.py   # DRF serializers (DTO ↔ JSON)
      views.py         # DRF views
      urls.py          # HTTP routing

    tests/
      test_models.py   # Unit: model tests
      test_logic.py    # Unit: domain logic tests
      test_api.py      # Unit: facade tests
      test_presentation.py  # Integration: DRF tests
      test_tasks.py    # Integration: Celery tests
      BUILD.bazel      # Bazel targets: :tests_unit, :tests_integration
```

### Why this layout?

* Matches Django conventions → low friction
* Keeps business logic separate from HTTP concerns
* Keeps app root clean
* Provides an explicit, enforced boundary (`api/`)
* Scales with Bazel’s dependency graph

## Repo layout

```text
posthog/               # Legacy monolith code
platform/              # Shared platform code
  integregrations/     # Webhook etc. for non-product things
    vercel/
  schemas/             # Shared Pydantic schemas
  auth/                # E.g. token utils
  http/                # Shared HTTP clients
  storage/             # Shared S3/GCS clients
  queue/               # Shared message queue helpers
  db/                  # Shared DB utilities
  observability/       # Logging, tracing, metrics
products/              # Product-specific apps
services/              # Independent backend services
tools/                 # Developer tooling, CLIs, scripts
```

### Services

* are their own deployment
* have their own domain possibly
* have logic that doesn’t belong to any specific product
* aren’t shared infrastructure
* aren’t cross-cutting glue
* aren’t frontend-facing “products”

These are not glue, because glue adapts other systems.  
They are not products, because no one interacts with them as a user-facing feature.  
They are not platform, because they own domain logic, not shared tooling.

### Platform

Cross-cutting glue and infrastructure: external adapters (Vercel), clients, shared libs. Must not import products/services.

Why platform must not call product facades:

* If platform imports and calls product facades, platform becomes a hidden orchestrator
* it must know which products exist
* it must route events to product logic
* it accumulates product-specific conditionals
* dependency direction flips (platform → products)
* cycles become likely over time

That destroys the "platform is foundational" property and makes boundaries brittle.

### Tools

Developer tooling: CLIs, linters, formatters, code generators, scaffolding scripts. Not imported by runtime code. Can be standalone packages or internal utilities.

# 4. DTOs as Dataclasses

DTOs are **stable, framework-free Python dataclasses**.

### Characteristics:

* No Django imports
* Immutable (`frozen=True`)
* Small, hashable, ideal for Bazel
* Serve as internal contracts
* Used by facades as inputs/outputs

### Example

```python
@dataclass(frozen=True)
class Artifact:
    id: UUID
    project_id: int
    content_hash: str
    storage_path: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime
```

DTOs **should not depend on**:

* Django models
* DRF serializers
* Request objects

If a DTO’s input and output shapes are identical → reuse the same dataclass.

---

# 5. Facades: The Public API Surface

Each app exposes a single structured API via `backend/api/api.py`.

This is the **only** module other apps are allowed to import.

### Responsibilities

* Accept DTOs as input parameters
* Call domain logic (`logic.py`)
* Convert Django models → DTOs
* Enforce transactions where needed
* Remain thin and stable

### Anti-responsibilities

**Do NOT:**

* Implement business logic
* Import DRF, HTTP, serializers
* Expose Django models
* Return ORM instances or QuerySets
* Leak internal implementation details

### Example facade method

```python
class ArtifactAPI:
    @staticmethod
    def create(params: CreateArtifact) -> Artifact:
        instance = logic.create_artifact(params)
        return Artifact.from_model(instance)
```

---

# 6. Domain Logic (backend/logic.py)

Business logic lives here.

Examples:

* Deduplication rules
* Domain invariants
* Cross-field validations
* Idempotency

### Why?

* Facades must stay thin and stable
* Presentation should not contain domain rules
* DTOs remain pure data
* Bazel recognizes logic as internal implementation

This is the **heart** of the module.

---

# 7. Presentation Layer (DRF)

Located in `backend/presentation/`.

Responsibilities:

* Validate incoming JSON (via DRF serializers)
* Convert incoming JSON → DTOs
* Call facade methods
* Convert DTOs → JSON responses
* No business logic

### Why not mix with domain or facade?

* Keeps HTTP concerns decoupled
* Allows reusing domain logic for:

  * async tasks
  * CLI
  * future services

### Serializer generation

Serializers for outgoing responses can be auto-generated from DTOs.

### Don't API views leak implementation?

No, because:

* Views only call facades
* Facades return DTOs, not models

So it's the responsibility of the API developer to keep logic and implementation separate and only use facades. This way, the presentation layer remains decoupled from internal details. We can still run isolated tests on the domain logic while being sure that when our facade has not changed, anything outside the module is unaffected.

---

# 8. Isolation, No-Leak Rules & Django Foreign Key Considerations (for Developers)

To keep architecture clean, developers must follow:

### ❌ Forbidden

* One app importing another app’s `models.py`
* Using a model across boundaries
* Importing anything from `backend/logic.py` outside the app
* Importing views/serializers from another app
* Returning ORM objects from facades
* Calling internal functions of another module

### ✔ Allowed

* Importing `myapp.backend.api` from another module
* Returning DTOs from facades
* Calling domain logic only from inside the same app
* Letting presentation call facade functions

### ⚠ Special Note on Django Foreign Keys

Django allows establishing `ForeignKey` relationships between models across apps. This is still allowed, but with important caveats. ForeignKey relations create **implicit reverse dependencies**, even if you never use them.

Example:

```python
# visual_review/backend/models.py
project = models.ForeignKey(Project, ...)
```

Even if your app never calls `Project`, Django will auto-generate:

* reverse relations (e.g. `project.visualreview_set`)
* migration dependencies
* app loading order dependencies

This violates isolation:

* Reverse relations leak internal implementation details
* Creates hidden dependencies across apps
* Makes selective testing harder
* Makes boundaries unclear to developers

### Rule:

**A Django app may have ForeignKeys *to* external apps (unless those are also strictly isolated), but other apps must not reference models *inside* this app.**

If you need reverse access, use:

* explicit API calls (`OtherAppAPI.list_for_project(project_id)`) rather than ORM traversal
* explicit DTO returns instead of model access

This preserves clean boundaries.

---

This prevents:

* Hidden dependencies
* Coupling across apps
* Test explosion
* Data-layer leaks

---

# 9. Bazel Targets & Test Structure

Each product has two BUILD.bazel files generated by `hogli product:bootstrap`:

## backend/BUILD.bazel

Four targets with visibility enforcement:

```python
:contract    # DTOs, domain_types - public to all products
:impl        # facade, logic, models - private (+ integration tests)
:presentation # DRF views/serializers - private
:tasks       # Celery entrypoints - private
```

**Visibility rules:**

* `:contract` → `["//products:__subpackages__"]` - any product can depend on it
* `:impl` → `["//products/{product}:__subpackages__", "//products:integration_tests"]`
* `:presentation`, `:tasks` → `["//products/{product}:__subpackages__"]`

**Dependency rules for `:contract` (keep it pure):**

* No Django imports (`from django.*`)
* No DRF imports (`from rest_framework.*`)
* Use stdlib for errors, not `django.core.exceptions`
* No `DTO.from_model()` methods - put conversion in `:impl`

## backend/tests/BUILD.bazel

Two test targets:

```python
:tests_unit         # test_models.py, test_logic.py, test_api.py
:tests_integration  # test_presentation.py, test_tasks.py
```

**Test file naming (hardcoded in BUILD):**

| File | Target | When it runs |
|------|--------|--------------|
| `test_models.py` | `:tests_unit` | Own `:impl` changes |
| `test_logic.py` | `:tests_unit` | Own `:impl` changes |
| `test_api.py` | `:tests_unit` | Own `:impl` changes |
| `test_presentation.py` | `:tests_integration` | Own `:presentation` or other `:impl` changes |
| `test_tasks.py` | `:tests_integration` | Own `:tasks` or other `:impl` changes |

**Adding new test files:** Edit `backend/tests/BUILD.bazel` and add to appropriate `srcs` list.

## How selective testing works

```text
other_product:tests_unit
       ↓ depends on
visual_review:contract  (dtos.py, domain_types.py)
       ↓ does NOT depend on
visual_review:impl      (logic.py, models.py)
```

**Scenario: Change `visual_review/logic.py`**

* `visual_review:tests_unit` → reruns ✓
* `visual_review:tests_integration` → reruns ✓
* `other_product:tests_unit` → does NOT rerun (only depends on `:contract`)
* `other_product:tests_integration` → reruns (depends on `visual_review:impl`)

## CI commands

```bash
# Run unit tests only (fast, for PRs)
bazel test //products/...:tests_unit

# Run all tests
bazel test //products/...

# Run specific product
bazel test //products/visual_review/...
```

---

# 10. Summary

This document outlines the **future direction** of our codebase:

* Django-idiomatic layout with modular boundaries
* Dataclass DTOs as stable contracts
* Thin facades as the only public interface
* Domain logic isolated and testable
* DRF presentation decoupled from core logic
* Bazel as the long-term test and build orchestrator

This architecture:

* Reduces coupling
* Enables selective testing
* Prepares us for monorepo-scale tooling
* Keeps the system maintainable as we grow
