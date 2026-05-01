# Iconik Storage Locator - v5_0_0

v5.0.0 is the simple/fast locator release:

- Paste one Iconik asset link, share link, or asset UUID.
- Get the S3 URI directly in Terminal.
- If the storage URL cannot be converted to `s3://bucket/key`, the tool prints
  the best fallback URL returned by Iconik.
- For local, Lucid Link, or other non-S3 storage, the tool shows the storage
  path from Iconik file metadata when available.
- Located URI lines include online/offline status.
- `Output` / `Outputs` include only online storage locations.
- CSV/TSV batch mode is still available for advanced workflows.

The runtime follows the dependency-free style from `versions/4_5_0` and the
packaged deliverables follow the dual-Mac executable pattern from v2.0.3.

## Deliverables

After build:

- `dist/iconik_locator_5_0_0_arm64`
- `dist/iconik_locator_5_0_0_arm64.zip`
- `dist/iconik_locator_5_0_0_x86_64`
- `dist/iconik_locator_5_0_0_x86_64.zip`
- `dist/checksums.txt`

## Dependencies

Runtime:

- Packaged executable: none.
- Source script: Python standard library only.

Build time:

- PyInstaller only.
- The build script reuses the v2.0.3 build virtual environments when present.

XLSX is intentionally not supported. Save Excel workbooks as CSV for batch mode.

## Quick Single Lookup

Default output is `S3`.

```sh
./dist/iconik_locator_5_0_0_arm64 "https://app.iconik.io/asset/<asset-id>"
```

Terminal output starts with the located URI:

```text
Located URI
[ONLINE] s3://bucket/path/to/file.mov

Output
s3://bucket/path/to/file.mov
```

If Iconik exposes offline or missing replicas, they remain visible in
`Located URIs` but are excluded from `Output` / `Outputs`:

```text
Located URIs
[ONLINE] s3://bucket/path/to/file.mov
[OFFLINE] Lucid Link/01_Production/05_Stunts/example.mov

Output
s3://bucket/path/to/file.mov
```

For copy/paste or shell workflows:

```sh
./dist/iconik_locator_5_0_0_arm64 --uri-only "https://app.iconik.io/asset/<asset-id>"
```

or:

```sh
./dist/iconik_locator_5_0_0_arm64 --quiet "https://app.iconik.io/asset/<asset-id>"
```

Copy the first URI to the macOS clipboard:

```sh
./dist/iconik_locator_5_0_0_arm64 --copy "https://app.iconik.io/asset/<asset-id>"
```

## Output Formats

```sh
--output S3
--output HTTPS
--output FULL
```

`S3` is the default. `HTTPS` strips presigned query parameters. `FULL` preserves
the full presigned URL returned by Iconik.

## Multi-Asset And Multi-Source Behavior

Share links:

```sh
--multi ERROR
--multi FIRST
--multi ALL
```

Multiple storage locations for the selected file:

```sh
--multi-files ERROR
--multi-files FIRST
--multi-files ALL
```

Defaults:

- `--multi ERROR`
- `--multi-files ALL`

## Advanced CSV/TSV Batch

```sh
./dist/iconik_locator_5_0_0_arm64 \
  --input ~/Downloads/iconik_links.csv \
  --column 0 \
  --out ~/Downloads/iconik_links_with_storage.csv
```

The output file includes:

- `StoragePath`
- `StorageStatus`
- `OfflineStorageLocations`
- `Error`
- `MultiInserted`
- `MultiTotalAssets`
- `AssetID`
- `AssetTitle`

Batch mode uses a small worker pool by default:

```sh
--workers 6
```

## Build

```sh
chmod +x build_macos_both_v_5_0_0.sh
./build_macos_both_v_5_0_0.sh
```
