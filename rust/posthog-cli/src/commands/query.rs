use anyhow::Error;
use clap::Subcommand;

use crate::{
    tui::query::start_query_editor,
    utils::{auth::load_token, query::run_query},
};

#[derive(Debug, Subcommand)]
pub enum QueryCommand {
    /// Start the interactive query editor
    Editor {
        #[arg(long, default_value = "false")]
        /// Don't print the final query to stdout
        no_print: bool,
        #[arg(long, default_value = "false")]
        /// Print out query debug information, as well as showing query results
        debug: bool,
        #[arg(long, default_value = "false")]
        /// Run the final query and print the results as json lines to stdout
        execute: bool,
    },
    /// Run a query directly, and print the results as json lines to stdout
    Run {
        /// The query to run
        query: String,
        #[arg(long)]
        /// Print the returned json, rather than just the results
        debug: bool,
    },
}

pub fn query_command(host: &str, query: &QueryCommand) -> Result<(), Error> {
    let creds = load_token()?;

    match query {
        QueryCommand::Editor {
            no_print,
            debug,
            execute,
        } => {
            let res = start_query_editor(host, creds.clone(), *debug)?;
            if !no_print {
                println!("Final query: {}", res);
            }
            if *execute {
                let query_endpoint = format!("{}/api/environments/{}/query", host, creds.env_id);
                let res = run_query(&query_endpoint, &creds.token, &res)??;
                for result in res.results {
                    println!("{}", serde_json::to_string(&result)?);
                }
            }
        }
        QueryCommand::Run { query, debug } => {
            let query_endpoint = format!("{}/api/environments/{}/query", host, creds.env_id);
            let res = run_query(&query_endpoint, &creds.token, query)??;
            if *debug {
                println!("{}", serde_json::to_string_pretty(&res)?);
            } else {
                for result in res.results {
                    println!("{}", serde_json::to_string(&result)?);
                }
            }
        }
    };

    Ok(())
}
