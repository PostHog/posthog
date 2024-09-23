// tests/parser_tests.rs
use hogql_parser::parse_query;
use insta::assert_json_snapshot;
use std::fs;
use std::path::Path;

#[test]
fn test_queries() {
    let queries_dir = Path::new("tests/queries");
    for entry in fs::read_dir(queries_dir).expect("Failed to read queries directory") {
        let entry = entry.expect("Failed to read directory entry");
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("sql") {
            let query_name = path.file_stem().and_then(|s| s.to_str()).unwrap();
            let query = fs::read_to_string(&path).expect("Failed to read query file");
            let ast = parse_query(&query);
            assert_json_snapshot!(query_name, ast);
        }
    }
}

#[test]
fn test_select_with_and() {
    let query = "SELECT * FROM users WHERE active = true AND role = 'admin';";
    let ast = parse_query(query);
    assert_json_snapshot!(ast);
}

#[test]
fn test_select_with_or() {
    let query = "SELECT id FROM orders WHERE status = 'pending' OR status = 'processing';";
    let ast = parse_query(query);
    assert_json_snapshot!(ast);
}

#[test]
fn test_invalid_query() {
    let query = "SELECT FROM WHERE;";
    let result = std::panic::catch_unwind(|| parse_query(query));
    assert!(result.is_err(), "Parser should panic on invalid query");
}
