use std::fmt::Display;
use std::io::{Cursor, Read};

use axum::async_trait;
use symbolic::common::Name;
use symbolic::debuginfo::Archive;
use symbolic::demangle::{Demangle, DemangleOptions};
use symbolic::symcache::{SymCache, SymCacheConverter};
use zip::ZipArchive;

use crate::{
    error::{AppleError, ResolveError},
    symbol_store::{Fetcher, Parser},
};

pub struct ParsedAppleSymbols {
    symcache_data: Vec<u8>,
}

pub struct AppleProvider {}

#[derive(Debug, Clone)]
pub enum AppleRef {}

#[async_trait]
impl Fetcher for AppleProvider {
    type Ref = AppleRef;
    type Fetched = Vec<u8>;
    type Err = ResolveError;

    async fn fetch(&self, _: i32, _: AppleRef) -> Result<Vec<u8>, Self::Err> {
        unreachable!("AppleRef is impossible to construct, so cannot be passed")
    }
}

#[async_trait]
impl Parser for AppleProvider {
    type Source = Vec<u8>;
    type Set = ParsedAppleSymbols;
    type Err = ResolveError;

    async fn parse(&self, source: Self::Source) -> Result<ParsedAppleSymbols, ResolveError> {
        // CLI uploads raw zip data directly
        ParsedAppleSymbols::from_dsym_zip(source)
    }
}

impl ParsedAppleSymbols {
    pub fn from_dsym_zip(zip_data: Vec<u8>) -> Result<Self, ResolveError> {
        let cursor = Cursor::new(zip_data);
        let mut archive =
            ZipArchive::new(cursor).map_err(|e| AppleError::ParseError(e.to_string()))?;

        let dwarf_data = Self::extract_dwarf_from_zip(&mut archive)?;

        let symcache_data = Self::convert_to_symcache(&dwarf_data)?;

        Ok(Self { symcache_data })
    }

    fn extract_dwarf_from_zip(archive: &mut ZipArchive<Cursor<Vec<u8>>>) -> Result<Vec<u8>, ResolveError> {
        for i in 0..archive.len() {
            let mut file = archive
                .by_index(i)
                .map_err(|e| AppleError::ParseError(e.to_string()))?;

            let name = file.name().to_string();

            if name.contains("/Contents/Resources/DWARF/") && !name.ends_with('/') {
                let mut data = Vec::new();
                file.read_to_end(&mut data)
                    .map_err(|e| AppleError::ParseError(e.to_string()))?;
                return Ok(data);
            }
        }

        Err(AppleError::ParseError("No DWARF file found in dSYM bundle".to_string()).into())
    }

    fn convert_to_symcache(dwarf_data: &[u8]) -> Result<Vec<u8>, ResolveError> {
        let archive =
            Archive::parse(dwarf_data).map_err(|e| AppleError::ParseError(e.to_string()))?;

        let obj = archive
            .objects()
            .next()
            .ok_or_else(|| AppleError::ParseError("No objects in archive".to_string()))?
            .map_err(|e| AppleError::ParseError(e.to_string()))?;

        let mut converter = SymCacheConverter::new();
        converter
            .process_object(&obj)
            .map_err(|e| AppleError::ParseError(e.to_string()))?;

        let mut buffer = Vec::new();
        converter
            .serialize(&mut Cursor::new(&mut buffer))
            .map_err(|e| AppleError::ParseError(e.to_string()))?;

        Ok(buffer)
    }

    pub fn lookup(&self, addr: u64) -> Result<Option<SymbolInfo>, ResolveError> {
        let symcache = SymCache::parse(&self.symcache_data)
            .map_err(|e| AppleError::ParseError(e.to_string()))?;

        let lookup_result = symcache.lookup(addr).next();

        match lookup_result {
            Some(result) => {
                // Demangle Swift/C++ symbols for readability
                let raw_name = result.function().name_for_demangling();
                let symbol = raw_name
                    .demangle(DemangleOptions::complete())
                    .unwrap_or_else(|| raw_name.to_string());

                Ok(Some(SymbolInfo {
                    symbol,
                    filename: result
                        .file()
                        .map(|f| f.full_path().to_string())
                        .unwrap_or_default(),
                    line: result.line(),
                }))
            }
            None => Ok(None),
        }
    }
}

#[derive(Debug, Clone)]
pub struct SymbolInfo {
    pub symbol: String,
    pub filename: String,
    pub line: u32,
}

impl Display for AppleRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "AppleRef")
    }
}
