# Iconik Storage Locator — v2_0_3

## What’s new in v2_0_3

This release focuses on **preferences**, **multi-asset behavior**, and **friendliness**:

- **First-run preferences** (stored and reused):
  - How to handle **share links** that resolve to multiple assets:
    - `ERROR` – show an error and ask for a single asset
    - `FIRST` – resolve only the first asset in the share
    - `ALL` – resolve all assets in the share
  - How to handle **multi-source files** (same file stored at multiple locations):
    - `ERROR` – show an error if multiple paths exist
    - `FIRST` – use only the first storage path
    - `ALL` – return all storage paths (default)
- **Interactive updates at any time**:
  - `--multi ERROR|FIRST|ALL`
  - `--multi-files ERROR|FIRST|ALL`
  - Can be used **alone** (just update preference) or in front of a URL/UUID/CSV/XLSX (update + run).
- **Friendlier messaging & prompts**:
  - Welcome text on first loop.
  - Clear column confirmation:
    > “Which column contains the links or IDs you would like to locate? (Enter to use suggested: …)”
  - Clear output path confirmation:
    > “Please confirm the output file path (Enter to use suggested)”
  - “Would you like to look up another?” instead of a terse prompt.
- **Excel write bug fixed**:
  - Uses `myfile.tmp.xlsx` instead of `myfile.xlsx.tmp`, so pandas/openpyxl can detect the correct engine.
  - Offers CSV fallback if writing XLSX fails.

All v2.0+ behavior is preserved, including:

- Dark “phosphor” terminal theme (if Rich is installed).
- Support for single URLs/UUIDs and **batch CSV/XLSX**.
- Output formats: `HTTPS`, `S3`, or `FULL` (presigned).
- Newline-joined storage paths for multi-source files.

---

## Quick start (single URL/ID)

1. Run the script or compiled executable.
2. On first run you’ll be asked for:

   - `App-ID`
   - `Auth-Token` (masked with asterisks)
   - How to handle:
     - **multi-asset shares**
     - **multi-source files**

   These are saved to:

   - **macOS**:  
     `~/Library/Application Support/IconikLocator/config.json`

3. You’ll see:

   ```text
   Welcome to Iconik Storage Locator!
