"""
Unit tests for iconik_locator core functions.

Covers parse_target(), presigned_to_s3(), and reverse_lookup()
without requiring network access or live API credentials.
"""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add the dev directory to the path so we can import the module.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dev"))

import iconik_locator as loc  # noqa: E402


# ──────────────────────────────────────────────────────────────────
# parse_target()
# ──────────────────────────────────────────────────────────────────

class TestParseTarget(unittest.TestCase):

    # Asset URLs
    def test_asset_url(self):
        url = "https://app.iconik.io/asset/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.assertEqual(loc.parse_target(url), ("asset", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

    def test_asset_url_trailing_slash(self):
        url = "https://app.iconik.io/asset/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/"
        self.assertEqual(loc.parse_target(url), ("asset", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

    def test_assets_plural(self):
        url = "https://app.iconik.io/assets/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.assertEqual(loc.parse_target(url), ("asset", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

    # Collection URLs
    def test_collection_url(self):
        url = "https://app.iconik.io/collection/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.assertEqual(loc.parse_target(url), ("collection", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

    # Share URLs
    def test_share_url(self):
        url = "https://app.iconik.io/share/ABCDE12345"
        self.assertEqual(loc.parse_target(url), ("share", "ABCDE12345"))

    def test_short_share_url(self):
        url = "https://app.iconik.io/u/XYZ-abc_123"
        self.assertEqual(loc.parse_target(url), ("share", "XYZ-abc_123"))

    # S3 URIs → reverse lookup
    def test_s3_uri(self):
        uri = "s3://my-bucket/path/to/file.mov"
        self.assertEqual(loc.parse_target(uri), ("reverse", uri))

    def test_s3_uri_uppercase(self):
        uri = "S3://MY-BUCKET/PATH/FILE.MXF"
        self.assertEqual(loc.parse_target(uri), ("reverse", uri))

    # Bare UUIDs
    def test_bare_uuid(self):
        uid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.assertEqual(loc.parse_target(uid), ("asset", uid))

    # Share codes (non-UUID, non-URL, non-S3)
    def test_share_code(self):
        self.assertEqual(loc.parse_target("ABCDEF"), ("share", "ABCDEF"))

    # Edge cases
    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            loc.parse_target("")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ValueError):
            loc.parse_target("   ")

    def test_quoted_input_stripped(self):
        url = '"https://app.iconik.io/asset/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"'
        self.assertEqual(loc.parse_target(url), ("asset", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

    def test_unrecognized_https_url_raises(self):
        with self.assertRaises(ValueError):
            loc.parse_target("https://example.com/something/random")


# ──────────────────────────────────────────────────────────────────
# presigned_to_s3()
# ──────────────────────────────────────────────────────────────────

class TestPresignedToS3(unittest.TestCase):

    def test_virtual_hosted_style(self):
        url = "https://mybucket.s3.us-east-1.amazonaws.com/path/to/key.mov?X-Amz-Signature=abc"
        result = loc.presigned_to_s3(url)
        self.assertEqual(result, "s3://mybucket/path/to/key.mov")

    def test_path_style(self):
        url = "https://s3.us-west-2.amazonaws.com/mybucket/key.mov?X-Amz-Signature=abc"
        result = loc.presigned_to_s3(url)
        self.assertEqual(result, "s3://mybucket/key.mov")

    def test_wasabi(self):
        url = "https://storage.wasabisys.com/mybucket/file.mp4"
        result = loc.presigned_to_s3(url)
        self.assertEqual(result, "s3://mybucket/file.mp4")

    def test_backblaze(self):
        url = "https://s3.us-west-004.backblazeb2.com/mybucket/file.mp4"
        result = loc.presigned_to_s3(url)
        self.assertEqual(result, "s3://mybucket/file.mp4")

    def test_cloudflare_r2(self):
        url = "https://account.cloudflarestorage.com/mybucket/file.mp4"
        result = loc.presigned_to_s3(url)
        self.assertEqual(result, "s3://mybucket/file.mp4")

    def test_passthrough_for_non_s3(self):
        url = "https://cdn.example.com/video.mp4"
        result = loc.presigned_to_s3(url)
        # Should still attempt best-effort conversion
        self.assertIsInstance(result, str)


# ──────────────────────────────────────────────────────────────────
# reverse_lookup()  — mocked API
# ──────────────────────────────────────────────────────────────────

class TestReverseLookup(unittest.TestCase):

    def _mock_client(self, post_responses):
        """Create a mock IconikClient that returns canned responses."""
        client = MagicMock()
        client.auth = MagicMock()
        client.auth.host = "https://app.iconik.io"
        client.post = MagicMock(side_effect=post_responses)
        client.storage_map = MagicMock(return_value={})
        return client

    def test_exact_path_match(self):
        asset_obj = {"id": "aaa-bbb", "title": "Test Asset"}
        client = self._mock_client([{"objects": [asset_obj]}])
        result = loc.reverse_lookup(client, "s3://mybucket/path/to/file.mov")
        self.assertEqual(result["type"], "reverse_list")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["id"], "aaa-bbb")

    def test_fallback_to_filename(self):
        # First call (exact path) returns empty, second (filename) returns match.
        asset_obj = {"id": "ccc-ddd", "title": "Fallback Asset"}
        client = self._mock_client([{"objects": []}, {"objects": [asset_obj]}])
        result = loc.reverse_lookup(client, "s3://mybucket/deep/path/file.mov")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["title"], "Fallback Asset")
        # Verify two POST calls were made (path then filename).
        self.assertEqual(client.post.call_count, 2)

    def test_no_results(self):
        client = self._mock_client([{"objects": []}, {"objects": []}])
        result = loc.reverse_lookup(client, "s3://mybucket/deep/path/missing.mov")
        self.assertEqual(result["results"], [])

    def test_no_fallback_when_key_is_bare_filename(self):
        # When key == filename (no directory), fallback should NOT fire.
        client = self._mock_client([{"objects": []}])
        result = loc.reverse_lookup(client, "s3://mybucket/file.mov")
        self.assertEqual(result["results"], [])
        # Only one POST call — no fallback because filename == key.
        self.assertEqual(client.post.call_count, 1)

    def test_invalid_uri_raises(self):
        client = self._mock_client([])
        with self.assertRaises(ValueError):
            loc.reverse_lookup(client, "not-an-s3-uri")

    def test_no_filter_in_payload(self):
        """No filter structure should be in the search payload."""
        asset_obj = {"id": "eee-fff", "title": "Asset"}
        client = self._mock_client([{"objects": [asset_obj]}])
        result = loc.reverse_lookup(client, "s3://mybucket-production/key.mov")
        call_args = client.post.call_args
        payload = call_args[0][1]
        self.assertNotIn("filter", payload)
        self.assertNotIn("search_fields", payload)
        self.assertEqual(result["results"][0]["id"], "eee-fff")
        self.assertEqual(result["bucket"], "mybucket-production")

    def test_query_uses_field_scoped_syntax(self):
        """Verify query uses files.path:\"key\" format that Iconik expects."""
        client = self._mock_client([{"objects": [{"id": "x", "title": "X"}]}])
        loc.reverse_lookup(client, "s3://bucket/path/to/file.mov")
        payload = client.post.call_args[0][1]
        self.assertEqual(payload["query"], 'files.path:"path/to/file.mov"')
        self.assertNotIn("search_fields", payload)

    def test_special_characters_in_key(self):
        """Verify special characters in S3 key don't crash the lookup."""
        # Two responses: exact path (empty) + filename fallback (empty).
        client = self._mock_client([{"objects": []}, {"objects": []}])
        result = loc.reverse_lookup(client, 's3://bucket/path/with"quotes.mov')
        self.assertEqual(result["type"], "reverse_list")


if __name__ == "__main__":
    unittest.main()
