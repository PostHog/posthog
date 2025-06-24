# Marketing Analytics Adapter Architecture

## Overview

The marketing analytics query runner has been refactored to use an extensible adapter pattern. This allows for easy addition of new marketing data sources without modifying existing code.

## Architecture Components

### 1. Base Adapter (`adapters/base.py`)

All marketing sources implement the `MarketingSourceAdapter` abstract base class:

```python
class MarketingSourceAdapter(ABC):
    @abstractmethod
    def validate(self) -> ValidationResult

    @abstractmethod
    def build_query(self, context: QueryContext) -> Optional[str]

    @abstractmethod
    def get_source_type(self) -> str
```

### 2. Concrete Adapters

#### Google Ads Adapter (`adapters/google_ads.py`)

-   Handles JOIN between campaign and stats tables
-   Implements existing Google Ads query logic exactly
-   Validates required table structure

#### External Table Adapter (`adapters/external_table.py`)

-   Handles both managed and self-managed external tables
-   Implements existing external table query logic exactly
-   Validates source map schema requirements

#### Meta Ads Adapter (`adapters/meta_ads.py`) - _Example_

-   Demonstrates single-table structure (vs Google Ads multi-table)
-   Shows how easy it is to add new sources

### 3. Factory (`adapters/factory.py`)

The `MarketingSourceFactory` handles:

-   **Source Discovery**: Finds all available data sources
-   **Adapter Creation**: Creates appropriate adapter for each source
-   **Validation**: Filters to only valid adapters
-   **Query Building**: Combines all adapter queries into union

## Benefits

### ✅ **Preserves Existing Behavior**

-   Final query output is **identical** to current implementation
-   All existing logic moved to appropriate adapters
-   Zero breaking changes to API or results

### ✅ **Easy Extension**

Adding a new marketing source requires only:

```python
# 1. Create new adapter
class LinkedInAdsAdapter(MarketingSourceAdapter):
    def get_source_type(self) -> str:
        return "LinkedInAds"

    def validate(self) -> ValidationResult:
        # Validation logic

    def build_query(self, context: QueryContext) -> Optional[str]:
        # Query building logic

# 2. Register with factory
MarketingSourceFactory.register_adapter('LinkedInAds', LinkedInAdsAdapter)

# 3. Add to constants.py
VALID_NATIVE_MARKETING_SOURCES = ['GoogleAds', 'MetaAds', 'LinkedInAds']
```

### ✅ **Separation of Concerns**

-   **Google Ads logic** → `GoogleAdsAdapter`
-   **External table logic** → `ExternalTableAdapter`
-   **Meta Ads logic** → `MetaAdsAdapter`
-   **Discovery & coordination** → `MarketingSourceFactory`

### ✅ **Better Testing**

-   Each adapter can be unit tested independently
-   Mock adapters can be created for testing
-   Validation logic is isolated and testable

### ✅ **Runtime Registration**

-   New adapters can be registered at runtime
-   Plugin-like architecture for extensions
-   No need to modify core files for new sources

## Migration Impact

### Files Modified

-   ✅ **Main query runner**: Simplified to use factory
-   ✅ **Constants/Utils**: Extracted for reuse
-   ✅ **New adapter files**: All logic moved here

### Files Removed

-   ❌ **~200 lines** of duplicated validation/query building code
-   ❌ **Complex source processing methods**
-   ❌ **Hardcoded source-specific logic**

### Backward Compatibility

-   ✅ **100% compatible** - same queries generated
-   ✅ **Same API** - no changes to external interface
-   ✅ **Same results** - identical output structure

## Future Extensions

This architecture easily supports:

-   **TikTok Ads**: Single table structure like Meta
-   **LinkedIn Ads**: Professional network advertising
-   **Twitter Ads**: Social media advertising
-   **Custom Sources**: Any user-defined marketing data
-   **Hybrid Sources**: Sources that combine multiple platforms

Each new source is just a new adapter implementing the standard interface.

## Performance

-   **Query generation**: Same performance (logic just moved)
-   **Validation**: More efficient (fail-fast per adapter)
-   **Caching**: Can cache adapter validation results
-   **Parallel processing**: Future capability to validate adapters in parallel
