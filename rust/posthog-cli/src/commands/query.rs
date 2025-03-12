use anyhow::Error;
use clap::ValueEnum;
use crossterm::event::{self, Event};
use ratatui::{
    layout::Constraint,
    style::{Color, Style, Stylize},
    widgets::{Row, Table, TableState},
    Frame,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

// TODO - we could formalise a lot of this and move it into posthog-rs, tbh

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryRequest {
    query: Query,
    refresh: QueryRefresh,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Query {
    HogQLQuery { query: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryRefresh {
    Blocking,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HogQLQueryResponse {
    pub cache_key: Option<String>,
    pub cache_target_age: Option<String>,
    pub clickhouse: Option<String>, // Clickhouse query text
    #[serde(default, deserialize_with = "null_is_empty")]
    pub columns: Vec<String>, // Columns returned from the query
    pub error: Option<String>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub explain: Vec<String>,
    #[serde(default, rename = "hasMore", deserialize_with = "null_is_false")]
    pub has_more: bool,
    pub hogql: Option<String>, // HogQL query text
    #[serde(default, deserialize_with = "null_is_false")]
    pub is_cached: bool,
    pub last_refresh: Option<String>, // Last time the query was refreshed
    pub next_allowed_client_refresh_time: Option<String>, // Next time the client can refresh the query
    pub offset: Option<i64>,                              // Offset of the query
    pub query: Option<String>,                            // Query text
    #[serde(default, deserialize_with = "null_is_empty")]
    pub types: Vec<(String, String)>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub results: Vec<Vec<Value>>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub timings: Vec<Timing>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HogQLQueryErrorResponse {
    pub code: String,
    pub detail: String,
    #[serde(rename = "type")]
    pub error_type: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Timing {
    k: String,
    t: f64,
}

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum OutputMode {
    Print,
    Tui,
}

pub fn run_query(host: &str, to_run: &str, output: OutputMode) -> Result<(), Error> {
    let client = reqwest::blocking::Client::new();
    let creds = crate::utils::auth::load_token()?;
    let query_endpoint = format!("{}/api/environments/{}/query", host, creds.env_id);

    let request = QueryRequest {
        query: Query::HogQLQuery {
            query: to_run.to_string(),
        },
        refresh: QueryRefresh::Blocking,
    };

    let response = client
        .post(&query_endpoint)
        .json(&request)
        .bearer_auth(creds.token)
        .send()?;

    let code = response.status();
    let body = response.text()?;

    let value: Value = serde_json::from_str(&body)?;

    if code.is_client_error() {
        let error: HogQLQueryErrorResponse = serde_json::from_value(value)?;
        println!("{}", serde_json::to_string_pretty(&error)?);
        return Ok(());
    }

    let response: HogQLQueryResponse = serde_json::from_value(value)?;

    match output {
        OutputMode::Print => {
            for res in response.results {
                println!("{}", serde_json::to_string(&res)?);
            }
        }
        OutputMode::Tui => {
            draw_output(&response)?;
        }
    }

    Ok(())
}

fn draw_output(response: &HogQLQueryResponse) -> Result<(), Error> {
    let mut terminal = ratatui::init();
    let mut table_state = TableState::default();

    loop {
        let draw_frame = |f: &mut Frame| draw_table(f, response, &mut table_state);
        terminal.draw(draw_frame).expect("failed to draw frame");
        if matches!(event::read().expect("failed to read event"), Event::Key(_)) {
            break;
        }
    }
    ratatui::restore();
    Ok(())
}

fn draw_table(f: &mut Frame, response: &HogQLQueryResponse, table_state: &mut TableState) {
    let cols = &response.columns;
    let widths = cols.iter().map(|_| Constraint::Fill(1)).collect::<Vec<_>>();
    let mut rows: Vec<Row> = Vec::with_capacity(response.results.len());
    for row in &response.results {
        let mut row_data = Vec::with_capacity(cols.len());
        for _ in cols {
            let value = row[row_data.len()].to_string();
            row_data.push(value.to_string());
        }
        rows.push(Row::new(row_data));
    }
    let table = Table::new(rows, widths)
        .column_spacing(1)
        .header(Row::new(cols.clone()).style(Style::new().bold().bg(Color::LightBlue)))
        .block(
            ratatui::widgets::Block::default()
                .title("Query Results (press any key to exit)")
                .title_style(Style::new().bold().fg(Color::White).bg(Color::DarkGray))
                .borders(ratatui::widgets::Borders::ALL)
                .border_style(Style::new().fg(Color::White).bg(Color::DarkGray)),
        )
        .row_highlight_style(Style::new().bold().bg(Color::Blue))
        .highlight_symbol(">>");

    f.render_stateful_widget(table, f.area(), table_state);
}

fn null_is_empty<'de, D, T>(deserializer: D) -> Result<Vec<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: serde::Deserialize<'de>,
{
    let opt = Option::deserialize(deserializer)?;
    match opt {
        Some(v) => Ok(v),
        None => Ok(Vec::new()),
    }
}

fn null_is_false<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let opt = Option::deserialize(deserializer)?;
    match opt {
        Some(v) => Ok(v),
        None => Ok(false),
    }
}
