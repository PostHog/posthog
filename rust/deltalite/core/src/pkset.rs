//! Multi-column primary-key hash set with SQL NULL semantics.
//!
//! Keys are encoded with arrow-row's `RowConverter`, which gives a byte-comparable,
//! type-aware encoding of a tuple of arrays. Equality on the encoded bytes is exactly
//! equality on the tuple values, provided both sides were encoded with the same
//! converter (hence the same data types) -- which is why callers must cast both the
//! source batch and every existing row group to the table schema first.
//!
//! SQL semantics that matter here: `NULL = NULL` is *not* true. A source row with a NULL
//! in any PK column can therefore never match a target row, so it must be excluded from
//! the set; and a target row with a NULL in any PK column can never be matched, so it is
//! never probed. Getting this wrong silently corrupts tables, so it is handled
//! explicitly on both sides rather than left to the encoding.

use std::collections::HashSet;
use std::sync::Arc;

use arrow_array::{Array, RecordBatch};
use arrow_row::{RowConverter, SortField};
use arrow_schema::SchemaRef;

use crate::errors::{Error, Result};

/// A hash set of primary-key tuples with SQL NULL semantics (NULL never matches).
pub struct PkSet {
    converter: RowConverter,
    keys: HashSet<Vec<u8>>,
    pk_indices: Vec<usize>,
    /// Number of source rows skipped because they carry a NULL PK component.
    pub null_pk_rows: usize,
}

/// True where the row has no NULL in any of `cols` (i.e. the row is matchable).
fn matchable_mask(cols: &[Arc<dyn Array>], num_rows: usize) -> Vec<bool> {
    let mut mask = vec![true; num_rows];
    for c in cols {
        if c.null_count() == 0 {
            continue;
        }
        for (i, m) in mask.iter_mut().enumerate() {
            if c.is_null(i) {
                *m = false;
            }
        }
    }
    mask
}

impl PkSet {
    /// Build an empty set keyed on `primary_keys`, whose types are taken from `schema`.
    pub fn new(schema: &SchemaRef, primary_keys: &[String]) -> Result<Self> {
        if primary_keys.is_empty() {
            return Err(Error::Generic("primary_keys must not be empty".into()));
        }
        let mut pk_indices = Vec::with_capacity(primary_keys.len());
        let mut fields = Vec::with_capacity(primary_keys.len());
        for pk in primary_keys {
            let idx = schema.index_of(pk).map_err(|_| {
                Error::SchemaMismatch(format!(
                    "primary key column '{pk}' not found in table schema"
                ))
            })?;
            pk_indices.push(idx);
            fields.push(SortField::new(schema.field(idx).data_type().clone()));
        }
        let converter =
            RowConverter::new(fields).map_err(|e| Error::Generic(format!("row converter: {e}")))?;
        Ok(Self {
            converter,
            keys: HashSet::new(),
            pk_indices,
            null_pk_rows: 0,
        })
    }

    fn pk_columns(&self, batch: &RecordBatch) -> Vec<Arc<dyn Array>> {
        self.pk_indices
            .iter()
            .map(|i| batch.column(*i).clone())
            .collect()
    }

    /// Insert every matchable row of the given PK columns, returning how many were
    /// already present (duplicates). `cols` must be the PK columns in primary-key
    /// order, with the table schema's PK types (see `contains_any_columns`). Lets
    /// callers feed the set from narrow column selections without materialising a
    /// full-width batch; the set persists across calls, so duplicates spanning calls
    /// are still counted.
    pub fn insert_columns(&mut self, cols: &[Arc<dyn Array>], num_rows: usize) -> Result<usize> {
        let mask = matchable_mask(cols, num_rows);
        let rows = self
            .converter
            .convert_columns(cols)
            .map_err(|e| Error::Generic(format!("row encode: {e}")))?;

        let mut duplicates = 0;
        for (i, matchable) in mask.iter().enumerate() {
            if !matchable {
                self.null_pk_rows += 1;
                continue;
            }
            if !self.keys.insert(rows.row(i).as_ref().to_vec()) {
                duplicates += 1;
            }
        }
        Ok(duplicates)
    }

    /// Whether *any* row of the given PK columns is present in the set.
    ///
    /// `cols` must be the PK columns in primary-key order, already cast to the same
    /// data types this set was built with (the table schema's PK types) -- otherwise the
    /// row encodings would not be comparable. Used by the per-file probe, which reads
    /// only the PK columns of a candidate file and therefore has no full-schema batch.
    pub fn contains_any_columns(&self, cols: &[Arc<dyn Array>], num_rows: usize) -> Result<bool> {
        if self.keys.is_empty() || num_rows == 0 {
            return Ok(false);
        }
        let mask = matchable_mask(cols, num_rows);
        let rows = self
            .converter
            .convert_columns(cols)
            .map_err(|e| Error::Generic(format!("row encode: {e}")))?;
        Ok((0..num_rows).any(|i| mask[i] && self.keys.contains(rows.row(i).as_ref())))
    }

    /// For each row of `batch`, whether it is replaced by a source row.
    pub fn contains_rows(&self, batch: &RecordBatch) -> Result<Vec<bool>> {
        let cols = self.pk_columns(batch);
        let mask = matchable_mask(&cols, batch.num_rows());
        let rows = self
            .converter
            .convert_columns(&cols)
            .map_err(|e| Error::Generic(format!("row encode: {e}")))?;

        Ok((0..batch.num_rows())
            .map(|i| mask[i] && self.keys.contains(rows.row(i).as_ref()))
            .collect())
    }

    /// Number of matchable keys in the set.
    pub fn len(&self) -> usize {
        self.keys.len()
    }

    /// True when the set holds no matchable key (e.g. every source row had a NULL PK).
    pub fn is_empty(&self) -> bool {
        self.keys.is_empty()
    }

    /// Resident bytes of the encoded key set (keys only, excluding `HashSet` overhead).
    /// Used by the source-size guard to report how large a rejected set was.
    pub fn approx_bytes(&self) -> usize {
        self.keys.iter().map(|k| k.len() + 48).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_array::{Int64Array, StringArray};
    use arrow_schema::{DataType, Field, Schema};

    fn schema() -> SchemaRef {
        Arc::new(Schema::new(vec![
            Field::new("id", DataType::Utf8, true),
            Field::new("tenant", DataType::Int64, true),
            Field::new("payload", DataType::Utf8, true),
        ]))
    }

    fn batch(ids: Vec<Option<&str>>, tenants: Vec<Option<i64>>) -> RecordBatch {
        let n = ids.len();
        RecordBatch::try_new(
            schema(),
            vec![
                Arc::new(StringArray::from(ids)),
                Arc::new(Int64Array::from(tenants)),
                Arc::new(StringArray::from(vec![Some("x"); n])),
            ],
        )
        .unwrap()
    }

    fn cols(b: &RecordBatch, names: &[&str]) -> Vec<Arc<dyn Array>> {
        names
            .iter()
            .map(|n| b.column_by_name(n).unwrap().clone())
            .collect()
    }

    #[test]
    fn null_pk_rows_are_never_inserted_and_never_match() {
        let s = schema();
        let mut set = PkSet::new(&s, &["id".to_string()]).unwrap();
        let src = batch(vec![Some("a"), None, None], vec![Some(1), Some(2), Some(3)]);
        let dup = set.insert_columns(&cols(&src, &["id"]), 3).unwrap();
        // Two NULL-keyed rows: not duplicates of each other (NULL != NULL), not inserted.
        assert_eq!(dup, 0);
        assert_eq!(set.null_pk_rows, 2);
        assert_eq!(set.len(), 1);

        // A NULL-keyed target row never matches, even though the set contains keys.
        let target = batch(vec![Some("a"), None], vec![Some(9), Some(9)]);
        assert_eq!(set.contains_rows(&target).unwrap(), vec![true, false]);
    }

    #[test]
    fn null_in_any_composite_component_excludes_the_row() {
        let s = schema();
        let pks = vec!["id".to_string(), "tenant".to_string()];
        let mut set = PkSet::new(&s, &pks).unwrap();
        let src = batch(
            vec![Some("a"), Some("b"), None],
            vec![Some(1), None, Some(3)],
        );
        set.insert_columns(&cols(&src, &["id", "tenant"]), 3)
            .unwrap();
        assert_eq!(set.len(), 1); // only ("a", 1)
        assert_eq!(set.null_pk_rows, 2);

        // Only the exact tuple matches.
        let target = batch(
            vec![Some("a"), Some("a"), Some("b")],
            vec![Some(1), Some(2), None],
        );
        assert_eq!(
            set.contains_rows(&target).unwrap(),
            vec![true, false, false]
        );
    }

    #[test]
    fn duplicates_are_counted_within_and_across_insert_calls() {
        let s = schema();
        let mut set = PkSet::new(&s, &["id".to_string()]).unwrap();
        let b1 = batch(vec![Some("a"), Some("a")], vec![Some(1), Some(2)]);
        assert_eq!(set.insert_columns(&cols(&b1, &["id"]), 2).unwrap(), 1);
        // The same key arriving in a later call is still a duplicate.
        let b2 = batch(vec![Some("a"), Some("b")], vec![Some(3), Some(4)]);
        assert_eq!(set.insert_columns(&cols(&b2, &["id"]), 2).unwrap(), 1);
        assert_eq!(set.len(), 2);
    }

    #[test]
    fn contains_any_columns_short_circuits_and_respects_nulls() {
        let s = schema();
        let mut set = PkSet::new(&s, &["id".to_string()]).unwrap();
        let src = batch(vec![Some("hit")], vec![Some(1)]);
        set.insert_columns(&cols(&src, &["id"]), 1).unwrap();

        let miss = batch(vec![Some("x"), None], vec![Some(1), Some(2)]);
        assert!(!set.contains_any_columns(&cols(&miss, &["id"]), 2).unwrap());
        let hit = batch(vec![Some("x"), Some("hit")], vec![Some(1), Some(2)]);
        assert!(set.contains_any_columns(&cols(&hit, &["id"]), 2).unwrap());
    }

    #[test]
    fn empty_set_matches_nothing() {
        let s = schema();
        let set = PkSet::new(&s, &["id".to_string()]).unwrap();
        assert!(set.is_empty());
        let target = batch(vec![Some("a")], vec![Some(1)]);
        assert_eq!(set.contains_rows(&target).unwrap(), vec![false]);
        assert!(!set
            .contains_any_columns(&cols(&target, &["id"]), 1)
            .unwrap());
    }

    #[test]
    fn missing_pk_column_is_a_schema_mismatch() {
        let s = schema();
        let err = match PkSet::new(&s, &["nope".to_string()]) {
            Err(e) => e,
            Ok(_) => panic!("expected an error for a missing PK column"),
        };
        assert!(matches!(err, Error::SchemaMismatch(_)));
    }
}
