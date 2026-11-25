//! Tabular topic files shared by the browser and view data bridge.
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeSet, path::Path};
/// Lowercase filename extension.
pub fn extension(path: &str) -> String {
    Path::new(path)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
}

#[derive(Serialize, Deserialize)]
/// Tabular projection for a topic file.
pub struct Table {
    /// Display column names.
    pub columns: Vec<String>,
    /// Cells in column order.
    pub rows: Vec<Vec<String>>,
}
fn text(cell: &Value) -> String {
    match cell {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        v => v.to_string(),
    }
}
/// Parse the first 201 records of a topic table.
pub fn read(path: &str, bytes: &[u8]) -> Result<Table> {
    if extension(path) != "json" {
        let mut reader = csv::ReaderBuilder::new()
            .delimiter(if extension(path) == "tsv" {
                b'\t'
            } else {
                b','
            })
            .from_reader(bytes);
        let columns = reader.headers()?.iter().map(str::to_owned).collect();
        let rows = reader
            .records()
            .take(201)
            .map(|r| Ok(r?.iter().map(str::to_owned).collect()))
            .collect::<Result<_>>()?;
        return Ok(Table { columns, rows });
    }
    let data: Value = serde_json::from_slice(bytes)?;
    if let (Some(cols), Some(rows)) = (data["columns"].as_array(), data["rows"].as_array()) {
        return Ok(Table {
            columns: cols.iter().map(text).collect(),
            rows: rows
                .iter()
                .take(201)
                .map(|r| {
                    let row = r.as_array().context("Expected a row of cells")?;
                    ensure!(
                        row.len() <= cols.len(),
                        "A row has more cells than the table has columns."
                    );
                    let mut cells: Vec<_> = row.iter().map(text).collect();
                    cells.resize(cols.len(), String::new());
                    Ok(cells)
                })
                .collect::<Result<_>>()?,
        });
    }
    let objects = data
        .as_array()
        .or_else(|| data["results"].as_array())
        .context("This JSON file contains no table. Open it in Files to read it.")?;
    ensure!(
        objects.iter().take(201).all(Value::is_object),
        "Expected a table of records"
    );
    let columns: Vec<_> = objects
        .iter()
        .take(201)
        .filter_map(Value::as_object)
        .flat_map(|r| r.keys().cloned())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let rows = objects
        .iter()
        .take(201)
        .map(|row| columns.iter().map(|col| text(&row[col])).collect())
        .collect();
    Ok(Table { columns, rows })
}
