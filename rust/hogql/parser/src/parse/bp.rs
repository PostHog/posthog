//! Pratt binding powers and the infix/postfix dispatch tables.
//!
//! The constants here are the only place precedence levels live; every
//! other module reads them through `pub(super)` re-exports rather than
//! hard-coding numbers. Higher value = tighter binding.

use std::borrow::Cow;

use crate::emit::Emitter;
use crate::lex::{Kw, TokenKind};

pub(super) const BP_ALIAS: u8 = 10;
pub(super) const BP_TERNARY: u8 = 20;
pub(super) const BP_BETWEEN: u8 = 30;
pub(super) const BP_OR: u8 = 40;
pub(super) const BP_AND: u8 = 50;
pub(super) const BP_NOT: u8 = 60;
pub(super) const BP_NULLISH: u8 = 70;
/// `IS [NOT] DISTINCT FROM` — declared *after* `IS NULL` in the grammar,
/// so it binds looser. `a IS NOT DISTINCT FROM b IS NOT NULL` parses
/// as `IsDistinctFrom(a, IsNull(b))` rather than `IsNull(IsDistinctFrom)`.
pub(super) const BP_IS_DISTINCT_FROM: u8 = 80;
/// `IS [NOT] NULL` — declared first in the grammar, binds tightest of
/// the `IS …` family.
pub(super) const BP_IS_NULL: u8 = 85;
/// `IGNORE NULLS` — declared *before* `IS NULL` in the grammar but
/// *after* arithmetic/comparison Precedence levels, so it binds
/// tighter than IS NULL and looser than `*` / `+` / comparisons.
pub(super) const BP_IGNORE_NULLS: u8 = 87;
pub(super) const BP_COMPARE: u8 = 90;
pub(super) const BP_ADDITIVE: u8 = 100;
pub(super) const BP_MULT: u8 = 110;
pub(super) const BP_UNARY_MINUS: u8 = 120;
pub(super) const BP_POSTFIX: u8 = 130;

#[derive(Debug, Clone, Copy)]
pub(super) enum InfixOp {
    Mul,
    Div,
    Mod,
    Add,
    Sub,
    Concat,
    Eq,
    NotEq,
    Lt,
    LtEq,
    Gt,
    GtEq,
    Regex,
    IRegex,
    NotRegex,
    NotIRegex,
    And,
    Or,
    Nullish,
}

pub(super) fn infix_bp(kind: TokenKind) -> Option<(u8, u8, InfixOp)> {
    let (lbp, op) = match kind {
        TokenKind::Asterisk => (BP_MULT, InfixOp::Mul),
        TokenKind::Slash => (BP_MULT, InfixOp::Div),
        TokenKind::Percent => (BP_MULT, InfixOp::Mod),
        TokenKind::Plus => (BP_ADDITIVE, InfixOp::Add),
        TokenKind::Dash => (BP_ADDITIVE, InfixOp::Sub),
        TokenKind::Concat => (BP_ADDITIVE, InfixOp::Concat),
        TokenKind::EqDouble | TokenKind::EqSingle => (BP_COMPARE, InfixOp::Eq),
        TokenKind::NotEq => (BP_COMPARE, InfixOp::NotEq),
        TokenKind::Lt => (BP_COMPARE, InfixOp::Lt),
        TokenKind::LtEq => (BP_COMPARE, InfixOp::LtEq),
        TokenKind::Gt => (BP_COMPARE, InfixOp::Gt),
        TokenKind::GtEq => (BP_COMPARE, InfixOp::GtEq),
        TokenKind::RegexSingle | TokenKind::RegexDouble => (BP_COMPARE, InfixOp::Regex),
        TokenKind::IRegexSingle | TokenKind::IRegexDouble => (BP_COMPARE, InfixOp::IRegex),
        TokenKind::NotRegex => (BP_COMPARE, InfixOp::NotRegex),
        TokenKind::NotIRegex => (BP_COMPARE, InfixOp::NotIRegex),
        TokenKind::Keyword(Kw::And) => (BP_AND, InfixOp::And),
        TokenKind::Keyword(Kw::Or) => (BP_OR, InfixOp::Or),
        TokenKind::Nullish => (BP_NULLISH, InfixOp::Nullish),
        _ => return None,
    };
    Some((lbp, lbp + 1, op))
}

pub(super) fn postfix_bp(kind: TokenKind) -> Option<u8> {
    match kind {
        TokenKind::LParen
        | TokenKind::LBracket
        | TokenKind::Dot
        | TokenKind::NullProperty
        | TokenKind::DoubleColon => Some(BP_POSTFIX),
        _ => None,
    }
}

pub(super) fn build_infix<E: Emitter>(
    emit: &E,
    op: InfixOp,
    lhs: E::Value,
    rhs: E::Value,
) -> E::Value {
    match op {
        InfixOp::Mul => emit.arith(lhs, "*", rhs),
        InfixOp::Div => emit.arith(lhs, "/", rhs),
        InfixOp::Mod => emit.arith(lhs, "%", rhs),
        InfixOp::Add => emit.arith(lhs, "+", rhs),
        InfixOp::Sub => emit.arith(lhs, "-", rhs),
        InfixOp::Concat => merge_concat(emit, lhs, rhs),
        InfixOp::Eq => emit.compare(lhs, "==", rhs),
        InfixOp::NotEq => emit.compare(lhs, "!=", rhs),
        InfixOp::Lt => emit.compare(lhs, "<", rhs),
        InfixOp::LtEq => emit.compare(lhs, "<=", rhs),
        InfixOp::Gt => emit.compare(lhs, ">", rhs),
        InfixOp::GtEq => emit.compare(lhs, ">=", rhs),
        InfixOp::Regex => emit.compare(lhs, "=~", rhs),
        InfixOp::IRegex => emit.compare(lhs, "=~*", rhs),
        InfixOp::NotRegex => emit.compare(lhs, "!~", rhs),
        InfixOp::NotIRegex => emit.compare(lhs, "!~*", rhs),
        InfixOp::And => merge_and_or(emit, "And", lhs, rhs),
        InfixOp::Or => merge_and_or(emit, "Or", lhs, rhs),
        InfixOp::Nullish => emit.call("ifNull", vec![lhs, rhs]),
    }
}

/// Flatten left-deep AND/OR trees into a single list to match the C++
/// visitor. Parsing `a AND b AND c` left-assoc gives nested And's; the C++
/// visitor pushes inner-And's children into the outer-And's list. Mirror
/// that here so JSON parity holds.
/// Flatten `||` chains the way cpp's `VISIT(ColumnExprPrecedence2)` does
/// for the CONCAT alt: `a || b || c` becomes `concat(a, b, c)` rather
/// than `concat(concat(a, b), c)`. Either side that's already a
/// `Call(name="concat", ...)` contributes its existing args.
pub(super) fn merge_concat<E: Emitter>(emit: &E, lhs: E::Value, rhs: E::Value) -> E::Value {
    let mut args: Vec<E::Value> = Vec::new();
    if is_concat_call(emit, &lhs) {
        if let Some(left_args) = emit.get_field(&lhs, "args").and_then(|v| emit.as_list(&v)) {
            args.extend(left_args);
        } else {
            args.push(lhs);
        }
    } else {
        args.push(lhs);
    }
    if is_concat_call(emit, &rhs) {
        if let Some(right_args) = emit.get_field(&rhs, "args").and_then(|v| emit.as_list(&v)) {
            args.extend(right_args);
        } else {
            args.push(rhs);
        }
    } else {
        args.push(rhs);
    }
    emit.call("concat", args)
}

fn is_concat_call<E: Emitter>(emit: &E, v: &E::Value) -> bool {
    if emit.node_kind(v).as_deref() != Some("Call") {
        return false;
    }
    emit.get_field(v, "name")
        .and_then(|name| emit.as_str(&name).map(Cow::into_owned))
        .as_deref()
        == Some("concat")
}

/// Flatten And/Or chains. cpp's `And`/`Or` visitor flattens BOTH operands, so `a AND b AND c` and `a AND (b AND c)` both produce a single flat `And` with three exprs — parenthesisation does not nest. We rebuild a fresh node from the extracted exprs so the outer pratt loop's `wrap_pos` can stamp the merged span (without the rebuild, idempotent `with_pos` would keep the pre-merge `[start, end]` and `a or b or c` would end at `b`'s position).
pub(super) fn merge_and_or<E: Emitter>(
    emit: &E,
    node: &str,
    lhs: E::Value,
    rhs: E::Value,
) -> E::Value {
    let mut exprs: Vec<E::Value> = Vec::new();
    extend_with_node_children(emit, &mut exprs, lhs, node);
    extend_with_node_children(emit, &mut exprs, rhs, node);
    if node == "And" {
        emit.and_(exprs)
    } else {
        emit.or_(exprs)
    }
}

/// If `v` is an `And`/`Or` node matching `node`, push its `exprs` children individually; otherwise push `v` itself.
fn extend_with_node_children<E: Emitter>(
    emit: &E,
    out: &mut Vec<E::Value>,
    v: E::Value,
    node: &str,
) {
    if emit.node_kind(&v).as_deref() == Some(node) {
        if let Some(children) = emit.get_field(&v, "exprs").and_then(|f| emit.as_list(&f)) {
            out.extend(children);
            return;
        }
    }
    out.push(v);
}

/// Function-call postfix on an already-parsed `lhs`. The cpp grammar
/// has two distinct alts for this position:
///
/// - `ColumnExprCallSelect` — single arg is a `selectSetStmt`. cpp
///   folds a `Field(chain=[name])` LHS into `Call(name, args=[select])`,
///   otherwise emits `ExprCall(expr=lhs, args=[select])`.
/// - `ColumnExprCall` — args are a regular `columnExprList`. cpp ALWAYS
///   emits `ExprCall(expr=lhs, args)`, never folds. The bare identifier
///   call shape (`f(1, 2)`) doesn't reach this rule because it matches
///   the earlier `ColumnExprFunction` alt and is emitted as `Call`
///   directly during identifier-led parsing.
///
/// We mirror that split here: fold only when args is exactly one
/// SelectQuery / SelectSetQuery / Placeholder and the LHS is a
/// single-element Field chain. `Placeholder` is included because
/// cpp's `selectSetStmt` grammar admits a bare `{X}` placeholder as
/// a set-stmt alternative, so `* ({x})` matches `ColumnExprCallSelect`
/// even when there's no SELECT keyword.
pub(super) fn fold_call_or_exprcall<E: Emitter>(
    emit: &E,
    lhs: E::Value,
    args: Vec<E::Value>,
) -> E::Value {
    let is_select_call = args.len() == 1
        && matches!(
            emit.node_kind(&args[0]).as_deref(),
            Some("SelectQuery") | Some("SelectSetQuery") | Some("Placeholder")
        );
    if is_select_call && emit.node_kind(&lhs).as_deref() == Some("Field") {
        if let Some(chain) = emit.get_field(&lhs, "chain").and_then(|c| emit.as_list(&c)) {
            if chain.len() == 1 {
                if let Some(name) = emit.as_str(&chain[0]).map(Cow::into_owned) {
                    return emit.call(&name, args);
                }
            }
        }
    }
    emit.expr_call(lhs, args)
}
