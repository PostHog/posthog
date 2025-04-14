#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR/../../../../..
bin/hoge rust/common/hogvm/src/bin/test.hog
cd $SCRIPT_DIR
cat test.hoge | cargo run --release --quiet --bin debug
