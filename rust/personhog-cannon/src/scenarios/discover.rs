use anyhow::{bail, Result};
use comfy_table::{presets::UTF8_FULL_CONDENSED, ContentArrangement, Table};
use owo_colors::OwoColorize;

use crate::cli::DiscoverArgs;
use crate::client::CannonClient;

pub async fn run(client: CannonClient, args: DiscoverArgs) -> Result<()> {
    if args.distinct_ids.is_empty() && args.person_ids.is_empty() {
        bail!("provide at least one of --distinct-ids or --person-ids");
    }

    let mut rows: Vec<PersonRow> = Vec::new();

    if !args.distinct_ids.is_empty() {
        println!(
            "Discovering {} distinct IDs for team {}...",
            args.distinct_ids.len(),
            args.team_id
        );
        let results = client
            .discover_by_distinct_ids(args.team_id, args.distinct_ids)
            .await?;

        for result in results {
            if let Some(person) = result.person {
                let props = parse_properties(&person.properties);
                let prop_count = props.as_object().map_or(0, |m| m.len());
                rows.push(PersonRow {
                    person_id: person.id,
                    uuid: person.uuid.clone(),
                    version: person.version,
                    is_identified: person.is_identified,
                    property_count: prop_count,
                    distinct_id: Some(result.distinct_id),
                });
            } else {
                println!(
                    "  {} distinct_id={:?} not found",
                    "MISS".yellow(),
                    result.distinct_id
                );
            }
        }
    }

    if !args.person_ids.is_empty() {
        println!(
            "Looking up {} person IDs for team {}...",
            args.person_ids.len(),
            args.team_id
        );
        let persons = client
            .get_persons(args.team_id, args.person_ids.clone())
            .await?;
        let found_ids: std::collections::HashSet<i64> = persons.iter().map(|p| p.id).collect();

        for person in persons {
            let props = parse_properties(&person.properties);
            let prop_count = props.as_object().map_or(0, |m| m.len());
            rows.push(PersonRow {
                person_id: person.id,
                uuid: person.uuid.clone(),
                version: person.version,
                is_identified: person.is_identified,
                property_count: prop_count,
                distinct_id: None,
            });
        }

        for id in &args.person_ids {
            if !found_ids.contains(id) {
                println!("  {} person_id={} not found", "MISS".yellow(), id);
            }
        }
    }

    if rows.is_empty() {
        println!("{}", "No persons found.".red());
        return Ok(());
    }

    let mut table = Table::new();
    table
        .load_preset(UTF8_FULL_CONDENSED)
        .set_content_arrangement(ContentArrangement::Dynamic)
        .set_header(vec![
            "person_id",
            "uuid",
            "version",
            "identified",
            "properties",
            "distinct_id",
        ]);

    for row in &rows {
        table.add_row(vec![
            row.person_id.to_string(),
            row.uuid[..8.min(row.uuid.len())].to_string(),
            row.version.to_string(),
            row.is_identified.to_string(),
            row.property_count.to_string(),
            row.distinct_id.as_deref().unwrap_or("-").to_string(),
        ]);
    }

    println!();
    println!("{table}");
    println!();

    let ids: Vec<String> = rows.iter().map(|r| r.person_id.to_string()).collect();
    println!(
        "Use with: {} --person-ids {}",
        "personhog-cannon blast".bold(),
        ids.join(",")
    );

    Ok(())
}

struct PersonRow {
    person_id: i64,
    uuid: String,
    version: i64,
    is_identified: bool,
    property_count: usize,
    distinct_id: Option<String>,
}

fn parse_properties(bytes: &[u8]) -> serde_json::Value {
    if bytes.is_empty() {
        return serde_json::Value::Object(serde_json::Map::new());
    }
    serde_json::from_slice(bytes).unwrap_or(serde_json::Value::Object(serde_json::Map::new()))
}
