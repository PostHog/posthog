// src/parser.rs
use crate::lexer::{Lexer, Token};
use serde::Serialize;

#[derive(Debug, Serialize)]
pub enum ASTNode {
    Program {
        declarations: Vec<ASTNode>,
    },
    Declaration(Box<ASTNode>),
    VarDecl {
        name: String,
        expr: Option<Box<ASTNode>>,
    },
    SelectStmt {
        distinct: bool,
        columns: Vec<ASTNode>,
        from: Option<Box<ASTNode>>,
        where_clause: Option<Box<ASTNode>>,
        group_by: Option<Vec<ASTNode>>,
        having: Option<Box<ASTNode>>,
        order_by: Option<Vec<ASTNode>>,
        limit: Option<Box<ASTNode>>,
        // Add other clauses as needed
    },
    ColumnExprAlias {
        expr: Box<ASTNode>,
        alias: String,
    },
    ColumnExprFunction {
        name: String,
        args: Vec<ASTNode>,
    },
    ColumnExprIdentifier(String),
    ColumnExprLiteral(Box<ASTNode>),
    ColumnExprBinaryOp {
        left: Box<ASTNode>,
        op: String,
        right: Box<ASTNode>,
    },
    ColumnExprUnaryOp {
        op: String,
        expr: Box<ASTNode>,
    },
    NumberLiteral(String),
    StringLiteral(String),
    OrderExpr {
        expr: Box<ASTNode>,
        order: Option<String>, // "ASC" or "DESC"
    },
    // Add other AST nodes as needed
}

pub struct Parser<'a> {
    lexer: Lexer<'a>,
    current_token: Token,
    peek_token: Token,
}

impl<'a> Parser<'a> {
    pub fn new(mut lexer: Lexer<'a>) -> Self {
        let current_token = lexer.get_next_token();
        let peek_token = lexer.get_next_token();
        Parser {
            lexer,
            current_token,
            peek_token,
        }
    }

    fn advance(&mut self) {
        self.current_token = std::mem::replace(&mut self.peek_token, self.lexer.get_next_token());
    }

    fn expect(&mut self, expected: &Token) {
        if &self.current_token == expected {
            self.advance();
        } else {
            panic!(
                "Expected token {:?}, but found {:?}",
                expected, self.current_token
            );
        }
    }

    pub fn parse(&mut self) -> ASTNode {
        self.parse_program()
    }

    fn parse_program(&mut self) -> ASTNode {
        let mut declarations = Vec::new();
        while self.current_token != Token::EOF {
            declarations.push(self.parse_declaration());
        }
        ASTNode::Program { declarations }
    }

    fn parse_declaration(&mut self) -> ASTNode {
        match &self.current_token {
            Token::Let => self.parse_var_decl(),
            Token::Select => self.parse_select_stmt(),
            // Add other declarations
            _ => panic!("Unexpected token: {:?}", self.current_token),
        }
    }

    fn parse_var_decl(&mut self) -> ASTNode {
        self.expect(&Token::Let);
        if let Token::Identifier(name) = &self.current_token {
            let var_name = name.clone();
            self.advance();
            let expr = if self.current_token == Token::Colon {
                self.advance();
                self.expect(&Token::EqSingle);
                Some(Box::new(self.parse_expression()))
            } else {
                None
            };
            ASTNode::VarDecl {
                name: var_name,
                expr,
            }
        } else {
            panic!("Expected identifier after 'let'");
        }
    }

    fn parse_select_stmt(&mut self) -> ASTNode {
        self.expect(&Token::Select);
        let distinct = if self.current_token == Token::Distinct {
            self.advance();
            true
        } else {
            false
        };
        let columns = self.parse_column_expr_list();

        let from = if self.current_token == Token::From {
            self.advance();
            Some(Box::new(self.parse_table_expr()))
        } else {
            None
        };

        let where_clause = if self.current_token == Token::Where {
            self.advance();
            Some(Box::new(self.parse_expression()))
        } else {
            None
        };

        let group_by = if self.current_token == Token::Group {
            self.advance();
            self.expect(&Token::By);
            Some(self.parse_column_expr_list())
        } else {
            None
        };

        let having = if self.current_token == Token::Having {
            self.advance();
            Some(Box::new(self.parse_expression()))
        } else {
            None
        };

        let order_by = if self.current_token == Token::Order {
            self.advance();
            self.expect(&Token::By);
            Some(self.parse_order_expr_list())
        } else {
            None
        };

        let limit = if self.current_token == Token::Limit {
            self.advance();
            Some(Box::new(self.parse_expression()))
        } else {
            None
        };

        ASTNode::SelectStmt {
            distinct,
            columns,
            from,
            where_clause,
            group_by,
            having,
            order_by,
            limit,
        }
    }

    fn parse_order_expr_list(&mut self) -> Vec<ASTNode> {
        let mut expressions = Vec::new();
        expressions.push(self.parse_order_expr());
        while self.current_token == Token::Comma {
            self.advance();
            expressions.push(self.parse_order_expr());
        }
        expressions
    }

    fn parse_order_expr(&mut self) -> ASTNode {
        let expr = self.parse_column_expr();
        let order = if self.current_token == Token::Asc || self.current_token == Token::Ascending {
            self.advance();
            Some("ASC".to_string())
        } else if self.current_token == Token::Desc || self.current_token == Token::Descending {
            self.advance();
            Some("DESC".to_string())
        } else {
            None
        };
        ASTNode::OrderExpr {
            expr: Box::new(expr),
            order,
        }
    }

    fn parse_column_expr_list(&mut self) -> Vec<ASTNode> {
        let mut columns = Vec::new();
        columns.push(self.parse_column_expr());
        while self.current_token == Token::Comma {
            self.advance();
            columns.push(self.parse_column_expr());
        }
        columns
    }

    fn parse_column_expr(&mut self) -> ASTNode {
        let mut expr = self.parse_column_expr_base();

        // Handle aliases
        if self.current_token == Token::As {
            self.advance();
            if let Token::Identifier(alias) = &self.current_token {
                let alias_name = alias.clone();
                self.advance();
                expr = ASTNode::ColumnExprAlias {
                    expr: Box::new(expr),
                    alias: alias_name,
                };
            } else {
                panic!("Expected identifier after AS");
            }
        } else if let Token::Identifier(alias) = &self.current_token {
            // Implicit alias
            let alias_name = alias.clone();
            self.advance();
            expr = ASTNode::ColumnExprAlias {
                expr: Box::new(expr),
                alias: alias_name,
            };
        }

        expr
    }

    fn parse_column_expr_base(&mut self) -> ASTNode {
        match &self.current_token {
            Token::Identifier(name) => {
                let func_name = name.clone();
                self.advance();
                if self.current_token == Token::LParen {
                    self.advance();
                    let args = if self.current_token != Token::RParen {
                        self.parse_column_expr_list()
                    } else {
                        Vec::new()
                    };
                    self.expect(&Token::RParen);
                    ASTNode::ColumnExprFunction {
                        name: func_name,
                        args,
                    }
                } else {
                    ASTNode::ColumnExprIdentifier(func_name)
                }
            }
            Token::StringLiteral(value) => {
                let string_value = value.clone();
                self.advance();
                ASTNode::ColumnExprLiteral(Box::new(ASTNode::StringLiteral(string_value)))
            }
            Token::NumberLiteral(value) => {
                let number_value = value.clone();
                self.advance();
                ASTNode::ColumnExprLiteral(Box::new(ASTNode::NumberLiteral(number_value)))
            }
            Token::LParen => {
                self.advance();
                let expr = self.parse_expression();
                self.expect(&Token::RParen);
                expr
            }
            _ => panic!("Unexpected token in column expression: {:?}", self.current_token),
        }
    }

    fn parse_table_expr(&mut self) -> ASTNode {
        match &self.current_token {
            Token::Identifier(name) => {
                let table_name = name.clone();
                self.advance();
                ASTNode::ColumnExprIdentifier(table_name)
            }
            Token::LParen => {
                self.advance();
                let subquery = self.parse_select_stmt();
                self.expect(&Token::RParen);
                subquery
            }
            _ => panic!("Unexpected token in table expression: {:?}", self.current_token),
        }
    }

    fn parse_expression(&mut self) -> ASTNode {
        self.parse_logical_or()
    }

    fn parse_logical_or(&mut self) -> ASTNode {
        let mut node = self.parse_logical_and();
        while self.current_token == Token::Or {
            self.advance();
            let right = self.parse_logical_and();
            node = ASTNode::ColumnExprBinaryOp {
                left: Box::new(node),
                op: "OR".to_string(),
                right: Box::new(right),
            };
        }
        node
    }

    fn parse_logical_and(&mut self) -> ASTNode {
        let mut node = self.parse_equality();
        while self.current_token == Token::And {
            self.advance();
            let right = self.parse_equality();
            node = ASTNode::ColumnExprBinaryOp {
                left: Box::new(node),
                op: "AND".to_string(),
                right: Box::new(right),
            };
        }
        node
    }

    fn parse_equality(&mut self) -> ASTNode {
        let mut node = self.parse_comparison();
        while matches!(self.current_token, Token::EqSingle | Token::EqDouble | Token::NotEq) {
            let op = match &self.current_token {
                Token::EqSingle => "=",
                Token::EqDouble => "==",
                Token::NotEq => "!=",
                _ => unreachable!(),
            }
            .to_string();
            self.advance();
            let right = self.parse_comparison();
            node = ASTNode::ColumnExprBinaryOp {
                left: Box::new(node),
                op,
                right: Box::new(right),
            };
        }
        node
    }

    fn parse_comparison(&mut self) -> ASTNode {
        let mut node = self.parse_term();
        while matches!(
            self.current_token,
            Token::Lt | Token::LtEq | Token::Gt | Token::GtEq
        ) {
            let op = match &self.current_token {
                Token::Lt => "<",
                Token::LtEq => "<=",
                Token::Gt => ">",
                Token::GtEq => ">=",
                _ => unreachable!(),
            }
            .to_string();
            self.advance();
            let right = self.parse_term();
            node = ASTNode::ColumnExprBinaryOp {
                left: Box::new(node),
                op,
                right: Box::new(right),
            };
        }
        node
    }

    fn parse_term(&mut self) -> ASTNode {
        let mut node = self.parse_factor();
        while matches!(self.current_token, Token::Plus | Token::Dash) {
            let op = match &self.current_token {
                Token::Plus => "+",
                Token::Dash => "-",
                _ => unreachable!(),
            }
            .to_string();
            self.advance();
            let right = self.parse_factor();
            node = ASTNode::ColumnExprBinaryOp {
                left: Box::new(node),
                op,
                right: Box::new(right),
            };
        }
        node
    }

    fn parse_factor(&mut self) -> ASTNode {
        let mut node = self.parse_unary();
        while matches!(
            self.current_token,
            Token::Asterisk | Token::Slash | Token::Percent
        ) {
            let op = match &self.current_token {
                Token::Asterisk => "*",
                Token::Slash => "/",
                Token::Percent => "%",
                _ => unreachable!(),
            }
            .to_string();
            self.advance();
            let right = self.parse_unary();
            node = ASTNode::ColumnExprBinaryOp {
                left: Box::new(node),
                op,
                right: Box::new(right),
            };
        }
        node
    }

    fn parse_unary(&mut self) -> ASTNode {
        if matches!(self.current_token, Token::Not | Token::Dash | Token::Plus) {
            let op = match &self.current_token {
                Token::Not => "NOT",
                Token::Dash => "-",
                Token::Plus => "+",
                _ => unreachable!(),
            }
            .to_string();
            self.advance();
            let expr = self.parse_unary();
            ASTNode::ColumnExprUnaryOp {
                op,
                expr: Box::new(expr),
            }
        } else {
            self.parse_primary()
        }
    }

    fn parse_primary(&mut self) -> ASTNode {
        match &self.current_token {
            Token::Identifier(_) => self.parse_column_expr(),
            Token::NumberLiteral(_) | Token::StringLiteral(_) => self.parse_literal(),
            Token::LParen => {
                self.advance();
                let expr = self.parse_expression();
                self.expect(&Token::RParen);
                expr
            }
            _ => panic!("Unexpected token in primary expression: {:?}", self.current_token),
        }
    }

    fn parse_literal(&mut self) -> ASTNode {
        match &self.current_token {
            Token::NumberLiteral(value) => {
                let num = value.clone();
                self.advance();
                ASTNode::NumberLiteral(num)
            }
            Token::StringLiteral(value) => {
                let str_val = value.clone();
                self.advance();
                ASTNode::StringLiteral(str_val)
            }
            _ => panic!("Unexpected token in literal: {:?}", self.current_token),
        }
    }
}

