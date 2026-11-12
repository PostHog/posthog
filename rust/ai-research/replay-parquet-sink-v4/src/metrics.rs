use metrics::counter;

use crate::columns::Index;
use crate::row::Rejection;

pub fn row_parsed(index: Index) {
    counter!("ai_research_v4_parquet_sink_rows_parsed_total", "index" => index.as_str())
        .increment(1);
}

pub fn row_rejected(reason: Rejection) {
    counter!("ai_research_v4_parquet_sink_rows_rejected_total", "reason" => reason.as_str())
        .increment(1);
}

pub fn invalid_column(index: Index, column: &str) {
    counter!(
        "ai_research_v4_parquet_sink_invalid_columns_total",
        "index" => index.as_str(),
        "column" => column.to_owned()
    )
    .increment(1);
}

pub fn rows_released(count: u64) {
    counter!("ai_research_v4_parquet_sink_rows_released_total").increment(count);
}

pub fn file_written(index: Index, rows: usize, bytes: usize) {
    let index = index.as_str();
    counter!("ai_research_v4_parquet_sink_files_written_total", "index" => index).increment(1);
    counter!("ai_research_v4_parquet_sink_rows_written_total", "index" => index)
        .increment(rows as u64);
    counter!("ai_research_v4_parquet_sink_bytes_written_total", "index" => index)
        .increment(bytes as u64);
}

pub fn write_error() {
    counter!("ai_research_v4_parquet_sink_write_errors_total").increment(1);
}

pub fn flushed(wrote_files: bool) {
    let outcome = if wrote_files { "written" } else { "empty" };
    counter!("ai_research_v4_parquet_sink_flushes_total", "outcome" => outcome).increment(1);
}

pub fn watermark_write(index: Index, outcome: &'static str) {
    counter!(
        "ai_research_v4_parquet_sink_watermark_writes_total",
        "index" => index.as_str(),
        "outcome" => outcome
    )
    .increment(1);
}
