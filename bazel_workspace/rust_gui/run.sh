#!/bin/bash

# Build and run the Rust GUI application using cargo
cd "$(dirname "$0")"
cargo run --release
