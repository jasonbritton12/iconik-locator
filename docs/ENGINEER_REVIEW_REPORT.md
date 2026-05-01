# Senior Engineer Review

**Component**: `iconik_locator.py` (v5_0_0)
**Reviewer Mode**: Strict Advisory-Only

## 1. Severity Ranking

- **Major** (Logic): Missing pagination in `list_files` and `list_share_assets` endpoints.
- **Major** (Logic): Potential crash in `make_location` if fallback storage map fails to populate `storage_name` and `storage_method` correctly, leading to missing keys (though `storage_metadata` handles this well, explicit dict access is a known risk vector if schema changes).
- **Minor** (Style/Readability): Hardcoded `SENSITIVE` config keys.

## 2. Edge Case Analysis

1.  **Pagination Gap (Race/Data Loss)**: The `/API/files/v1/assets/{asset_id}/files/` and `/API/acls/v1/shares/{share_id}/assets/` endpoints are paginated by Iconik. The current code (`self.get(f"/API/files/v1/assets/{asset_id}/files/")`) relies on the default page size (likely 10 or 100). If an asset has hundreds of files or a share has hundreds of assets, the locator will silently fail to check them all, potentially returning incomplete results or missing the `is_original` file if it's on a later page.
2.  **Config Directory Creation**: `os.makedirs(CONFIG_DIR, exist_ok=True)` in `ConfigStore.save` is safe, but the `os.chmod(CONFIG_PATH, 0o600)` can raise exceptions in edge-case environments (e.g., Windows network drives or specific permission boundaries), which is safely caught. Good defensive programming here.
3.  **Thread Safety**: In `batch_lookup`, the thread pool appends to `results_by_idx` dictionary from the main thread via `fut.result()`. This is completely thread-safe.

## 3. Concrete Fixes

### Fix 1: Missing Pagination in API Calls (Major)

The `list_files` and `list_share_assets` methods currently only fetch the first page of results. They should use a `while` loop with `next_url` parsing similar to the existing `list_storages` implementation.

```diff
--- a/dev/iconik_locator.py
+++ b/dev/iconik_locator.py
@@ -300,16 +300,30 @@
         except Exception:
             return {}
 
     def list_share_assets(self, share_id: str) -> List[Dict[str, Any]]:
         try:
-            data = self.get(f"/API/acls/v1/shares/{quote_path(share_id)}/assets/")
-            return objects_from(data)
+            assets: List[Dict[str, Any]] = []
+            path: Optional[str] = f"/API/acls/v1/shares/{quote_path(share_id)}/assets/?page=1&per_page=100"
+            while path:
+                data = self.get(path)
+                objects = objects_from(data)
+                if not objects:
+                    break
+                assets.extend(objects)
+                next_url = data.get("next_url") if isinstance(data, dict) else None
+                path = normalize_next_url(next_url, default_prefix=f"/API/acls/v1/shares/{quote_path(share_id)}/assets")
+            if assets:
+                return assets
         except FileNotFoundError:
             pass
         data = self.get(f"/API/acls/v1/shares/{quote_path(share_id)}/")
         ...
 
     def list_files(self, asset_id: str) -> List[Dict[str, Any]]:
-        data = self.get(f"/API/files/v1/assets/{asset_id}/files/")
-        return objects_from(data)
+        files: List[Dict[str, Any]] = []
+        path: Optional[str] = f"/API/files/v1/assets/{asset_id}/files/?page=1&per_page=100"
+        while path:
+            data = self.get(path)
+            objects = objects_from(data)
+            if not objects:
+                break
+            files.extend(objects)
+            next_url = data.get("next_url") if isinstance(data, dict) else None
+            path = normalize_next_url(next_url, default_prefix=f"/API/files/v1/assets/{asset_id}/files")
+        return files
```

### Fix 2: Resilient Interactive Prompts (Minor)
As noted in the UX review, `choose_column` can crash the CLI on a bad input. It should loop.

```diff
--- a/dev/iconik_locator.py
+++ b/dev/iconik_locator.py
@@ -881,12 +881,13 @@
         ui.info("Columns:")
         for idx, col in enumerate(columns):
             sample = rows[0].get(col, "") if rows else ""
             ui.info(f"  {idx}: {col}  score={scores.get(col, 0.0):.2f}  sample={sample[:80]}")
-        raw = ui.ask("Which column contains asset/share links or IDs? Enter index or name", suggested)
-        if raw.isdigit():
-            idx = int(raw)
-            if 0 <= idx < len(columns):
-                return columns[idx]
-        for col in columns:
-            if col == raw or col.lower() == raw.lower():
-                return col
-        raise RuntimeError(f"Column not found: {raw}")
+        while True:
+            raw = ui.ask("Which column contains asset/share links or IDs? Enter index or name", suggested)
+            if raw.isdigit():
+                idx = int(raw)
+                if 0 <= idx < len(columns):
+                    return columns[idx]
+            for col in columns:
+                if col == raw or col.lower() == raw.lower():
+                    return col
+            ui.err(f"Column not found: {raw}. Please try again.")
```

## 4. Verdict
`Request Changes`

The core implementation is highly robust, dependency-free, and handles HTTP retries/backoffs correctly. However, the missing pagination on core iteration endpoints is a functional gap for enterprise-scale assets/shares and needs to be addressed before a clean production sign-off.

### Required Actions Checklist
- [ ] Implement pagination looping for `list_files`.
- [ ] Implement pagination looping for `list_share_assets`.
- [ ] Update `choose_column` to use a retry loop for invalid interactive inputs.
