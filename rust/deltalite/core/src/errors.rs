//! Typed error hierarchy for deltalite.
//!
//! The Python binding crate maps each variant onto a dedicated exception class so
//! callers can branch on error *kind* instead of sniffing error text (the pattern the
//! existing `delta_table_helper.py` is stuck with for the Python package's errors).

pub type Result<T> = std::result::Result<T, Error>;

/// All errors deltalite can surface.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// Anything without a more specific classification.
    #[error("{0}")]
    Generic(String),

    /// The source batch cannot be reconciled with the table schema (unknown columns,
    /// uncastable types, missing PK/partition columns).
    #[error("{0}")]
    SchemaMismatch(String),

    /// The URI does not point at a loadable Delta table.
    #[error("{0}")]
    NotFound(String),

    /// The table declares features deltalite cannot safely rewrite (deletion vectors,
    /// column mapping, multiple partition columns).
    #[error("{0}")]
    Unsupported(String),

    /// The transaction layer exhausted its retries or hit a true logical conflict.
    #[error("{0}")]
    Conflict(String),

    /// The source batch (resident bytes + estimated PK-set size) exceeds the configured
    /// ceiling. Raised at the front door instead of growing RSS until the pod OOMs:
    /// deltalite's memory is bounded in the *target* by construction, but scales
    /// linearly with the *source*, and this is the guard on that term.
    #[error("{0}")]
    SourceTooLarge(String),
}

impl From<deltalake::DeltaTableError> for Error {
    fn from(e: deltalake::DeltaTableError) -> Self {
        use deltalake::DeltaTableError as D;
        match &e {
            D::NotATable(_) | D::InvalidTableLocation(_) => Error::NotFound(e.to_string()),
            D::SchemaMismatch { .. } => Error::SchemaMismatch(e.to_string()),
            // The transaction layer surfaces exhausted-retry / logical conflicts here.
            D::Transaction { .. } => Error::Conflict(e.to_string()),
            _ => Error::Generic(e.to_string()),
        }
    }
}

impl From<arrow_schema::ArrowError> for Error {
    fn from(e: arrow_schema::ArrowError) -> Self {
        Error::Generic(format!("arrow: {e}"))
    }
}

impl From<parquet::errors::ParquetError> for Error {
    fn from(e: parquet::errors::ParquetError) -> Self {
        Error::Generic(format!("parquet: {e}"))
    }
}

impl From<object_store::Error> for Error {
    fn from(e: object_store::Error) -> Self {
        Error::Generic(format!("object_store: {e}"))
    }
}

impl Error {
    /// Static label for metrics/tracing, one per variant. `&'static str` on purpose:
    /// per rust/CLAUDE.md, metric label values must never be freshly-allocated
    /// `String`s, and a fixed variant name needs no `Arc<str>` either.
    pub fn kind(&self) -> &'static str {
        match self {
            Error::Generic(_) => "generic",
            Error::SchemaMismatch(_) => "schema_mismatch",
            Error::NotFound(_) => "not_found",
            Error::Unsupported(_) => "unsupported",
            Error::Conflict(_) => "conflict",
            Error::SourceTooLarge(_) => "source_too_large",
        }
    }
}
