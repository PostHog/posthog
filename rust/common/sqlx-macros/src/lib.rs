//! Compile-time checked sqlx queries over mirrored table sets: one SQL
//! string with `{table}` placeholders expands to a `sqlx` macro per set,
//! selected at runtime by a `bool`. Usage and placeholder rules are in
//! the crate README.
//!
//! The executor call after `=>` is part of the macro because each `sqlx`
//! expansion has its own row type; awaiting inside each branch is what
//! lets the two unify.
//!
//! `op = "name"` prefixes both expansions with the query tag
//! `/* service='<crate>', operation='name' */` that pganalyze and pgcollector read.

use proc_macro::TokenStream;
use proc_macro2::TokenStream as TokenStream2;
use quote::quote;
use syn::parse::{Parse, ParseStream};
use syn::{parse_macro_input, Expr, Ident, LitStr, Token, Type};

const MIRROR_SUFFIX: &str = "_tmp";

struct MirroredQuery {
    row: Option<Type>,
    mirror: Expr,
    op: Option<LitStr>,
    sql: LitStr,
    args: Vec<Expr>,
    method: Ident,
    executor: TokenStream2,
}

impl MirroredQuery {
    fn parse(input: ParseStream, with_row: bool) -> syn::Result<Self> {
        let row = if with_row {
            let row: Type = input.parse()?;
            input.parse::<Token![,]>()?;
            Some(row)
        } else {
            None
        };
        let mirror: Expr = input.parse()?;
        input.parse::<Token![,]>()?;
        let op = if input.peek(Ident) && input.peek2(Token![=]) {
            let key: Ident = input.parse()?;
            if key != "op" {
                return Err(syn::Error::new(key.span(), "expected `op = \"...\"`"));
            }
            input.parse::<Token![=]>()?;
            let op: LitStr = input.parse()?;
            input.parse::<Token![,]>()?;
            Some(op)
        } else {
            None
        };
        let sql: LitStr = input.parse()?;
        let mut args = Vec::new();
        while input.peek(Token![,]) {
            input.parse::<Token![,]>()?;
            if input.peek(Token![=>]) {
                break;
            }
            args.push(input.parse::<Expr>()?);
        }
        input.parse::<Token![=>]>()?;
        let method: Ident = input.parse()?;
        let content;
        syn::parenthesized!(content in input);
        let executor: TokenStream2 = content.parse()?;
        Ok(Self {
            row,
            mirror,
            op,
            sql,
            args,
            method,
            executor,
        })
    }

    fn expand(self, sqlx_macro: TokenStream2) -> TokenStream2 {
        let (real, mirror) = match rewrite(&self.sql.value()) {
            Ok(pair) => pair,
            Err(message) => {
                return syn::Error::new(self.sql.span(), message).to_compile_error();
            }
        };
        let (real, mirror) = match &self.op {
            Some(op) => {
                // The using crate's rustc invocation carries its package name.
                let service = std::env::var("CARGO_PKG_NAME").unwrap_or_default();
                match tag(&service, &op.value()) {
                    Ok(prefix) => (format!("{prefix}{real}"), format!("{prefix}{mirror}")),
                    Err(message) => {
                        return syn::Error::new(op.span(), message).to_compile_error();
                    }
                }
            }
            None => (real, mirror),
        };
        let real = LitStr::new(&real, self.sql.span());
        let mirror = LitStr::new(&mirror, self.sql.span());
        let row = self.row.map(|row| quote!(#row,));
        let args = &self.args;
        let select = &self.mirror;
        let method = &self.method;
        let executor = &self.executor;
        quote! {
            if #select {
                #sqlx_macro(#row #mirror #(, #args)*).#method(#executor).await
            } else {
                #sqlx_macro(#row #real #(, #args)*).#method(#executor).await
            }
        }
    }
}

struct WithoutRow(MirroredQuery);
struct WithRow(MirroredQuery);

impl Parse for WithoutRow {
    fn parse(input: ParseStream) -> syn::Result<Self> {
        MirroredQuery::parse(input, false).map(Self)
    }
}

impl Parse for WithRow {
    fn parse(input: ParseStream) -> syn::Result<Self> {
        MirroredQuery::parse(input, true).map(Self)
    }
}

/// A value with a quote or a comment marker would end the tag early, so both are rejected.
fn tag(service: &str, operation: &str) -> Result<String, String> {
    for (what, value) in [("service", service), ("operation", operation)] {
        if value.is_empty()
            || !value
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.' | '/' | ':'))
        {
            return Err(format!(
                "query tag {what} {value:?} must be a plain identifier"
            ));
        }
    }
    Ok(format!(
        "/* service='{service}', operation='{operation}' */ "
    ))
}

fn rewrite(sql: &str) -> Result<(String, String), String> {
    let mut real = String::with_capacity(sql.len());
    let mut mirror = String::with_capacity(sql.len());
    let mut chars = sql.chars().peekable();
    let mut placeholders = 0;
    while let Some(c) = chars.next() {
        match c {
            '{' if chars.peek() == Some(&'{') => {
                chars.next();
                real.push('{');
                mirror.push('{');
            }
            '}' if chars.peek() == Some(&'}') => {
                chars.next();
                real.push('}');
                mirror.push('}');
            }
            '{' => {
                let mut name = String::new();
                loop {
                    match chars.next() {
                        Some('}') => break,
                        Some(ch) => name.push(ch),
                        None => return Err("unclosed `{` in mirrored query".to_string()),
                    }
                }
                let (real_name, mirror_name) = match name.split_once('|') {
                    Some((real_name, mirror_name)) => {
                        (real_name.to_string(), mirror_name.to_string())
                    }
                    None => (name.clone(), format!("{name}{MIRROR_SUFFIX}")),
                };
                for table in [&real_name, &mirror_name] {
                    if table.is_empty()
                        || !table
                            .chars()
                            .all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
                    {
                        return Err(format!("`{table}` is not a table identifier"));
                    }
                }
                real.push_str(&real_name);
                mirror.push_str(&mirror_name);
                placeholders += 1;
            }
            '}' => return Err("stray `}` in mirrored query; write `}}` for a literal".to_string()),
            _ => {
                real.push(c);
                mirror.push(c);
            }
        }
    }
    if placeholders == 0 {
        return Err(
            "mirrored query has no `{table}` placeholder; use sqlx::query! directly".to_string(),
        );
    }
    Ok((real, mirror))
}

#[proc_macro]
pub fn mirrored_query(input: TokenStream) -> TokenStream {
    let WithoutRow(query) = parse_macro_input!(input as WithoutRow);
    query.expand(quote!(::sqlx::query!)).into()
}

#[proc_macro]
pub fn mirrored_query_as(input: TokenStream) -> TokenStream {
    let WithRow(query) = parse_macro_input!(input as WithRow);
    query.expand(quote!(::sqlx::query_as!)).into()
}

#[proc_macro]
pub fn mirrored_query_scalar(input: TokenStream) -> TokenStream {
    let WithoutRow(query) = parse_macro_input!(input as WithoutRow);
    query.expand(quote!(::sqlx::query_scalar!)).into()
}

#[cfg(test)]
mod tests {
    use super::{rewrite, tag};

    #[test]
    fn the_tag_is_a_sqlcommenter_prefix_and_rejects_values_that_would_break_it() {
        assert_eq!(
            tag("personhog-identity", "merge_flip").unwrap(),
            "/* service='personhog-identity', operation='merge_flip' */ "
        );
        assert!(tag("personhog-identity", "it's").is_err());
        assert!(tag("", "x").is_err());
    }

    #[test]
    fn a_bare_placeholder_gets_the_mirror_suffix() {
        let (real, mirror) = rewrite("SELECT 1 FROM {lifecycle_op} o").unwrap();
        assert_eq!(real, "SELECT 1 FROM lifecycle_op o");
        assert_eq!(mirror, "SELECT 1 FROM lifecycle_op_tmp o");
    }

    #[test]
    fn an_explicit_pair_names_both_sides() {
        let (real, mirror) = rewrite("FROM {posthog_person|personhog_person_tmp}").unwrap();
        assert_eq!(real, "FROM posthog_person");
        assert_eq!(mirror, "FROM personhog_person_tmp");
    }

    #[test]
    fn doubled_braces_stay_literal() {
        let (real, mirror) = rewrite("SET request = '{{}}'::jsonb FROM {t}").unwrap();
        assert_eq!(real, "SET request = '{}'::jsonb FROM t");
        assert_eq!(mirror, "SET request = '{}'::jsonb FROM t_tmp");
    }

    #[test]
    fn malformed_placeholders_are_rejected() {
        assert!(rewrite("FROM {lifecycle_op").is_err());
        assert!(rewrite("FROM lifecycle_op}").is_err());
        assert!(rewrite("FROM {bad name}").is_err());
        assert!(rewrite("FROM lifecycle_op").is_err());
    }
}
