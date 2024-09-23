// src/bin/main.rs
use hogql_parser::parse_query;
use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        eprintln!("Usage: hogql_parser \"SQL QUERY\"");
        std::process::exit(1);
    }

    let query = &args[1];
    let ast = parse_query(query);
    println!("{}", serde_json::to_string_pretty(&ast).unwrap());
}
