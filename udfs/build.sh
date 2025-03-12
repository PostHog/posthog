#!/bin/sh

echo "Installing cross"
cargo install cross --git https://github.com/cross-rs/cross

echo "Building for x86_64"
cross build --target x86_64-unknown-linux-gnu --release

echo "Building for aarch64"
cross build --target aarch64-unknown-linux-gnu --release

echo "Copying executables to posthog/user_scripts"
archs=("x86_64" "aarch64")
targets=("x86_64-unknown-linux-gnu" "aarch64-unknown-linux-gnu")

for i in "${!archs[@]}"; do  
  SRC_DIR="target/${targets[$i]}/release"
  ARCH_SUFFIX="_${archs[$i]}"
    
  # loop over executables in the source directory
  file "$SRC_DIR"/* | grep executable | awk -F: '{print $1}' | while IFS= read -r exe_file; do
    base=$(basename "$exe_file") # get the filename
    dest_file="../posthog/user_scripts/${base}_${archs[$i]}"
    
    cp "$exe_file" "$dest_file"
    echo "Copied $exe_file to $dest_file"
  done
done


echo "Make sure to run udf_versioner.py"