use crate::metric_consts::{POSTGRES_ROWS_AFFECTED, POSTGRES_WRITE_ATTEMPTS};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum FrameWriteOutcome {
    Insert,
    Changed,
    Unchanged,
    Error,
}

impl FrameWriteOutcome {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Insert => "insert",
            Self::Changed => "changed",
            Self::Unchanged => "unchanged",
            Self::Error => "error",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SymbolSetWritePurpose {
    Data,
    AutomaticFailure,
    LastUsed,
    Invalidation,
    Cleanup,
}

impl SymbolSetWritePurpose {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Data => "symbol_data",
            Self::AutomaticFailure => "automatic_failure",
            Self::LastUsed => "last_used",
            Self::Invalidation => "invalidation",
            Self::Cleanup => "cleanup",
        }
    }

    const fn table(self) -> &'static str {
        match self {
            Self::Invalidation => "stack_frame",
            Self::Data | Self::AutomaticFailure | Self::LastUsed | Self::Cleanup => "symbol_set",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SymbolSetWriteOutcome {
    Written,
    Skipped,
    Error,
}

impl SymbolSetWriteOutcome {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Written => "written",
            Self::Skipped => "skipped",
            Self::Error => "error",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum PostgresMutation {
    Upsert,
    Update,
    Delete,
}

impl PostgresMutation {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Upsert => "upsert",
            Self::Update => "update",
            Self::Delete => "delete",
        }
    }
}

pub(crate) fn record_frame_write(outcome: FrameWriteOutcome, rows_affected: u64) {
    metrics::counter!(
        POSTGRES_WRITE_ATTEMPTS,
        "table" => "stack_frame",
        "purpose" => "frame_snapshot",
        "outcome" => outcome.as_str(),
    )
    .increment(1);

    record_rows_affected(
        "stack_frame",
        "frame_snapshot",
        PostgresMutation::Upsert,
        rows_affected,
    );
}

pub(crate) fn record_symbol_set_write(
    purpose: SymbolSetWritePurpose,
    outcome: SymbolSetWriteOutcome,
    mutation: PostgresMutation,
    rows_affected: u64,
) {
    metrics::counter!(
        POSTGRES_WRITE_ATTEMPTS,
        "table" => purpose.table(),
        "purpose" => purpose.as_str(),
        "outcome" => outcome.as_str(),
    )
    .increment(1);

    record_rows_affected(purpose.table(), purpose.as_str(), mutation, rows_affected);
}

fn record_rows_affected(
    table: &'static str,
    purpose: &'static str,
    mutation: PostgresMutation,
    rows_affected: u64,
) {
    if rows_affected == 0 {
        return;
    }

    metrics::counter!(
        POSTGRES_ROWS_AFFECTED,
        "table" => table,
        "purpose" => purpose,
        "mutation" => mutation.as_str(),
    )
    .increment(rows_affected);
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use metrics_util::debugging::DebuggingRecorder;

    use super::{
        record_frame_write, record_symbol_set_write, FrameWriteOutcome, PostgresMutation,
        SymbolSetWriteOutcome, SymbolSetWritePurpose,
    };
    use crate::metric_consts::{POSTGRES_ROWS_AFFECTED, POSTGRES_WRITE_ATTEMPTS};

    #[test]
    fn write_attribution_uses_only_bounded_labels() {
        let recorder = DebuggingRecorder::new();

        metrics::with_local_recorder(&recorder, || {
            for outcome in [
                FrameWriteOutcome::Insert,
                FrameWriteOutcome::Changed,
                FrameWriteOutcome::Unchanged,
                FrameWriteOutcome::Error,
            ] {
                record_frame_write(outcome, u64::from(outcome != FrameWriteOutcome::Error));
            }

            for purpose in [
                SymbolSetWritePurpose::Data,
                SymbolSetWritePurpose::AutomaticFailure,
                SymbolSetWritePurpose::LastUsed,
                SymbolSetWritePurpose::Invalidation,
                SymbolSetWritePurpose::Cleanup,
            ] {
                for outcome in [
                    SymbolSetWriteOutcome::Written,
                    SymbolSetWriteOutcome::Skipped,
                    SymbolSetWriteOutcome::Error,
                ] {
                    let mutation =
                        match purpose {
                            SymbolSetWritePurpose::Data
                            | SymbolSetWritePurpose::AutomaticFailure => PostgresMutation::Upsert,
                            SymbolSetWritePurpose::LastUsed => PostgresMutation::Update,
                            SymbolSetWritePurpose::Invalidation
                            | SymbolSetWritePurpose::Cleanup => PostgresMutation::Delete,
                        };
                    record_symbol_set_write(
                        purpose,
                        outcome,
                        mutation,
                        u64::from(outcome == SymbolSetWriteOutcome::Written),
                    );
                }
            }
        });

        let snapshot = recorder.snapshotter().snapshot().into_vec();
        let attempts = snapshot
            .iter()
            .filter(|(key, _, _, _)| key.key().name() == POSTGRES_WRITE_ATTEMPTS)
            .collect::<Vec<_>>();
        let rows = snapshot
            .iter()
            .filter(|(key, _, _, _)| key.key().name() == POSTGRES_ROWS_AFFECTED)
            .collect::<Vec<_>>();

        assert_eq!(attempts.len(), 19);
        assert_eq!(rows.len(), 6);

        let allowed_label_keys = HashSet::from(["table", "purpose", "outcome"]);
        let allowed_tables = HashSet::from(["stack_frame", "symbol_set"]);
        let allowed_purposes = HashSet::from([
            "frame_snapshot",
            "symbol_data",
            "automatic_failure",
            "last_used",
            "invalidation",
            "cleanup",
        ]);
        let allowed_outcomes = HashSet::from([
            "insert",
            "changed",
            "unchanged",
            "written",
            "skipped",
            "error",
        ]);

        for (key, _, _, _) in attempts {
            let labels = key
                .key()
                .labels()
                .map(|label| (label.key(), label.value()))
                .collect::<Vec<_>>();
            assert!(labels
                .iter()
                .all(|(key, _)| allowed_label_keys.contains(key)));
            assert!(labels
                .iter()
                .any(|(key, value)| *key == "table" && allowed_tables.contains(value)));
            assert!(labels
                .iter()
                .any(|(key, value)| *key == "purpose" && allowed_purposes.contains(value)));
            assert!(labels
                .iter()
                .any(|(key, value)| *key == "outcome" && allowed_outcomes.contains(value)));
        }

        let allowed_row_label_keys = HashSet::from(["table", "purpose", "mutation"]);
        let allowed_mutations = HashSet::from(["upsert", "update", "delete"]);
        let mut observed_mutations = HashSet::new();
        for (key, _, _, _) in rows {
            let labels = key
                .key()
                .labels()
                .map(|label| (label.key(), label.value()))
                .collect::<Vec<_>>();
            assert!(labels
                .iter()
                .all(|(key, _)| allowed_row_label_keys.contains(key)));
            let mutation = labels
                .iter()
                .find_map(|(key, value)| (*key == "mutation").then_some(*value))
                .expect("rows metric has a mutation label");
            assert!(allowed_mutations.contains(mutation));
            observed_mutations.insert(mutation);
        }
        assert_eq!(observed_mutations, allowed_mutations);
    }
}
