/// Like `Default`, but for test contexts. Provides sensible test defaults
/// (non-zero IDs, descriptive names, 100% rollout, etc.).
///
/// Unlike `Default`, `Mock` values are designed to be "obviously test data" --
/// for instance, `FeatureFlag::mock()` returns a flag with `key: "test_flag"`
/// and `active: true` rather than zero values.
pub trait Mock {
    fn mock() -> Self;
}

/// Create a mock of `Self` seeded from a value of type `T`.
///
/// Useful for converting between related types (e.g., building a
/// `FeatureFlagRow` from a `FeatureFlag` for database insertion tests)
/// or for ergonomic type coercions (e.g., `&str` → `Option<String>`).
pub trait MockFrom<T> {
    fn mock_from(value: T) -> Self;
}

/// The reciprocal of [`MockFrom`].
pub trait MockInto<T> {
    fn mock_into(self) -> T;
}

impl<T, U: MockFrom<T>> MockInto<U> for T {
    fn mock_into(self) -> U {
        U::mock_from(self)
    }
}

impl<T> MockFrom<T> for T {
    fn mock_from(value: T) -> Self {
        value
    }
}

// Primitive / standard-library conversions

impl MockFrom<&str> for String {
    fn mock_from(value: &str) -> Self {
        value.to_owned()
    }
}

impl<X> MockFrom<X> for Option<String>
where
    String: MockFrom<X>,
{
    fn mock_from(value: X) -> Self {
        Some(String::mock_from(value))
    }
}

/// Creates a mock instance of a type implementing [`Mock`], with optional field overrides.
///
/// # Usage
///
/// ```rust,ignore
/// // No overrides -- pure defaults
/// let flag = mock!(FeatureFlag);
///
/// // With field overrides
/// let flag = mock!(FeatureFlag, team_id: 42, key: "my_flag".mock_into());
///
/// // Nested mocks via MockInto
/// let flag = mock!(FeatureFlag,
///     filters: mock!(PropertyFilter, key: "country".mock_into()).mock_into()
/// );
///
/// // MockFrom -- create from another type
/// let row = mock!(FeatureFlagRow, from: flag.clone());
///
/// // MockFrom with additional overrides
/// let row = mock!(FeatureFlagRow, from: flag, key: "override".mock_into());
/// ```
#[macro_export]
macro_rules! mock {
    // No overrides
    ($T:path) => {
        <$T as $crate::utils::mock::Mock>::mock()
    };
    // MockFrom, no extra overrides (must precede the generic field-override arm)
    ($T:path, from: $source:expr) => {
        <$T as $crate::utils::mock::MockFrom<_>>::mock_from($source)
    };
    // MockFrom with field overrides
    ($T:path, from: $source:expr, $($field:ident : $value:expr),+ $(,)?) => {{
        let base = <$T as $crate::utils::mock::MockFrom<_>>::mock_from($source);
        $T { $($field: $value),+, ..base }
    }};
    // With field overrides via struct update syntax
    ($T:path, $($field:ident : $value:expr),+ $(,)?) => {{
        let base = <$T as $crate::utils::mock::Mock>::mock();
        $T { $($field: $value),+, ..base }
    }};
}
