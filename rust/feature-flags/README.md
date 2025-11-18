
# PostHog Feature Flags - Rust Implementation

This directory contains the Rust implementation of PostHog's feature flag evaluation system, including Python bindings for integration with the Django application.

## Overview

The feature flags Rust implementation provides high-performance feature flag evaluation that can be called from both:
1. The standalone Rust HTTP service
2. Python/Django code via PyO3 bindings

This allows PostHog to consolidate all flag-matching logic in Rust while maintaining compatibility with existing Python endpoints.

## Python Bindings

### Building the Python Extension

The Python bindings are optional and compiled only when the `python` feature is enabled.

#### Prerequisites

- Python 3.8 or later
- Rust toolchain (via rustup)
- maturin: `pip install maturin`

#### Development Build

Build and install the extension in development mode:

```bash
cd rust/feature-flags
maturin develop --features python
```

This will:
1. Compile the Rust code with the `python` feature enabled
2. Create a Python wheel
3. Install it in your current Python environment as `posthog_feature_flags_rs`

#### Production Build

For production, build optimized wheels:

```bash
cd rust/feature-flags
maturin build --release --features python
```

The wheel will be created in `target/wheels/`.

### Using from Python

#### Import

```python
from posthog.models.feature_flag.flag_matching_rust import get_all_feature_flags_with_details_rust
```

#### Function Signature

```python
def get_all_feature_flags_with_details_rust(
    team: Team,
    distinct_id: str,
    groups: Optional[dict[str, str]] = None,
    hash_key_override: Optional[str] = None,
    property_value_overrides: Optional[dict[str, Union[str, int]]] = None,
    group_property_value_overrides: Optional[dict[str, dict[str, Union[str, int]]]] = None,
    flag_keys: Optional[list[str]] = None,
) -> tuple[
    dict[str, Union[str, bool]],  # flag_values
    dict[str, dict],               # evaluation_reasons
    dict[str, object],             # flag_payloads
    bool,                          # errors_while_computing_flags
    Optional[dict[str, dict]]      # flag_details
]
```

#### Example Usage

```python
from posthog.models import Team
from posthog.models.feature_flag.flag_matching_rust import get_all_feature_flags_with_details_rust

team = Team.objects.get(id=1)
distinct_id = "user123"

flag_values, reasons, payloads, errors, details = get_all_feature_flags_with_details_rust(
    team=team,
    distinct_id=distinct_id,
    groups={"company": "acme_corp"},
    property_value_overrides={"email": "user@example.com"},
)

print(f"Feature flags for {distinct_id}: {flag_values}")
```

### Architecture

#### Core Components

- `src/flags/flag_matching.rs`: Core flag matching logic with `FeatureFlagMatcher`
- `src/python_bindings.rs`: PyO3 bindings for Python integration (compiled with `python` feature)
- `posthog/models/feature_flag/flag_matching_rust.py`: Python wrapper that calls the Rust implementation

#### Database Access

The implementation uses `PostgresRouter` to route queries to appropriate database instances:
- Persons reader/writer: For person-related queries
- Non-persons reader/writer: For flag definitions, cohorts, and other data

#### Type Conversions

Python → Rust conversions:
- `dict[str, str]` (groups) → `HashMap<String, Value>`
- `dict[str, Union[str, int]]` (properties) → `HashMap<String, Value>`
- `dict[str, dict[str, Union[str, int]]]` (group properties) → `HashMap<String, HashMap<String, Value>>`

Rust → Python conversions:
- `FlagsResponse` → tuple of `(flag_values, evaluation_reasons, flag_payloads, errors, flag_details)`

#### GIL Management

The Python bindings properly handle the Global Interpreter Lock (GIL):
1. Python objects are converted to Rust data structures while holding the GIL
2. The GIL is released using `py.allow_threads()` during async Rust operations
3. The GIL is re-acquired when converting results back to Python objects

This ensures Python code isn't blocked during flag evaluation.

### Troubleshooting

#### Import Error

```
ImportError: posthog_feature_flags_rs module not found
```

**Solution**: Build the module with `maturin develop --features python`

#### Type Errors

```
TypeError: argument 'groups': 'dict' object cannot be converted to 'PyDict'
```

**Solution**: Ensure you're passing native Python dicts, not custom dict-like objects

#### Database Connection Errors

```
Failed to create persons reader pool: ...
```

**Solution**: Check that Django database settings are properly configured and databases are accessible

# Testing

First, make sure docker compose is running (from main posthog repo), and test database exists:

```sh
docker compose -f ../docker-compose.dev.yml up -d
```

```sh
TEST=1 python manage.py setup_test_environment --only-postgres
```

We only need to run the above once, when the test database is created.

TODO: Would be nice to make the above automatic.

Then, run the tests:

```sh
cargo test --package feature-flags
```

## To watch changes

```sh
brew install cargo-watch
```

and then run:

```sh
cargo watch -x test --package feature-flags
```

To run a specific test:

```sh
cargo watch -x "test --package feature-flags --lib -- property_matching::tests::test_match_properties_math_operators --exact --show-output"
```

# Running

```sh
RUST_LOG=debug cargo run --bin feature-flags
```

# Format code

```sh
cargo fmt --package feature-flags
```
