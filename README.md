# Iconik Storage Locator

The Iconik Storage Locator is a tool designed to quickly find the physical storage location (S3 URIs, HTTPS URLs, or local paths) of assets in Iconik.

## Download Iconik Locator

Get the latest version below. Extract the `.zip` and run the executable from your terminal.

* [**Download for macOS (Apple Silicon / M1/M2/M3)**](https://github.com/jasonbritton12/iconik-locator/releases/latest/download/iconik_locator_arm64.zip)
* [**Download for macOS (Intel / x86_64)**](https://github.com/jasonbritton12/iconik-locator/releases/latest/download/iconik_locator_x86_64.zip)

> **Note:** If you get a security warning on macOS, you may need to go to *System Settings > Privacy & Security* to allow the application to run, or clear the quarantine attribute via terminal: `xattr -d com.apple.quarantine iconik_locator`

## Features

* Paste one Iconik asset link, share link, or asset UUID to get storage details.
* **Reverse Lookup**: Paste an `s3://` URI to instantly find its corresponding Iconik Asset URL.
* Get the S3 URI directly in Terminal.
* If the storage URL cannot be converted to `s3://bucket/key`, the tool prints the best fallback URL returned by Iconik.
* For local, Lucid Link, or other non-S3 storage, the tool shows the storage path from Iconik file metadata when available.
* Located URI lines include online/offline status.
* `Output` / `Outputs` include only online storage locations.
* **Interactive Mode**: Rapidly perform multiple lookups in succession seamlessly crossing between Iconik URLs and S3 URIs.
* Dependency-free runtime (Python standard library only).

## Deliverables

After build:

* `dist/iconik_locator_arm64`
* `dist/iconik_locator_arm64.zip`
* `dist/iconik_locator_x86_64`
* `dist/iconik_locator_x86_64.zip`
* `dist/checksums.txt`

## Quick Single Lookup

Default output is `S3`.

```sh
./dist/iconik_locator_arm64 "https://app.iconik.io/asset/<asset-id>"
```

Terminal output starts with the located URI:

```text
Located URI
[ONLINE] s3://bucket/path/to/file.mov

Output
s3://bucket/path/to/file.mov
```

If Iconik exposes offline or missing replicas, they remain visible in `Located URIs` but are excluded from `Output` / `Outputs`:

```text
Located URIs
[ONLINE] s3://bucket/path/to/file.mov
[OFFLINE] Lucid Link/01_Production/05_Stunts/example.mov

Output
s3://bucket/path/to/file.mov
```

### Bidirectional Lookup

The Locator can map from S3 back to Iconik seamlessly. Paste an `s3://` URI:

```sh
./dist/iconik_locator_arm64 "s3://bucket/path/to/file.mov"
```

The tool will return the mapped Iconik Assets:

```text
Located Iconik Assets
1

Asset
My Asset Title
00000000-0000-0000-0000-000000000000

Iconik URL
https://app.iconik.io/asset/00000000-0000-0000-0000-000000000000
```

### Options

* `--uri-only`: Print only the URI.
* `--quiet`: Minimal output.
* `--copy`: Copy the first URI to the macOS clipboard.

## Output Formats

```sh
--output S3
--output HTTPS
--output FULL
```

`S3` is the default. `HTTPS` strips presigned query parameters. `FULL` preserves the full presigned URL returned by Iconik.

## Multi-Asset And Multi-Source Behavior

Share links:

* `--multi ERROR` (Default)
* `--multi FIRST`
* `--multi ALL`

Multiple storage locations for the selected file:

* `--multi-files ERROR`
* `--multi-files FIRST`
* `--multi-files ALL` (Default)

## Interactive Mode

For high-speed, successive lookups, run the tool without an input argument to enter **Interactive Mode**:

```sh
./dist/iconik_locator_arm64
```

Simply paste an Iconik link or UUID and press Enter. The tool will display the results and immediately prompt for the next one. Type `help` for instructions or `q` to quit.

## Build

```sh
cd dev
chmod +x build.sh
./build.sh
```

## Project Structure

* `dev/`: Development source code and build scripts.
  * `iconik_locator.py`: Main script.
  * `build.sh`: macOS build script.
* `releases/`: Historical and packaged releases.
  * `v5.0.0/`: Legacy version.
  * `v6.0.0/`: Version 6.0.0 source.
* `docs/`: Additional documentation.
* `README.md`: This file.
