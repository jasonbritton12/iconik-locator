# Senior UX Design Review

**Target Audience:** Video editors, media managers, and technical operators managing media storage links via Iconik.
**End-User Primary Goal:** Quickly and reliably extract physical storage paths (S3, HTTP) from Iconik entities (Assets, Shares, Collections) via single inputs or bulk CSVs.

## 1. Verdict
`Request UX Changes`

## 2. Risk Tier
Risk Tier 5 (Conditional / Proceed with Caution)

## 3. Inferred Lifecycle Mode
**Mode:** `enterprise` (Internal Tooling)
**Confidence:** High
**Assumptions:** As an internal enterprise tool, reliability, clear error states, and bulk processing efficiency are paramount. The tool is used by professionals who value speed and predictability over elaborate onboarding.

## 4. Severity Ranking
- **Minor**: Interactive error recovery, Help discoverability, Input resilience.

## 5. Findings Log

**[Tier 5] [Minor] [Usability, Error Recovery] [Friction on typo in column selection] [Code Review] [High]**
* **Fix**: Introduce a retry loop for column selection rather than crashing.
* **Acceptance Criteria**: If a user enters an invalid column name/index in the interactive prompt, the CLI should print an error and ask again, rather than raising a `RuntimeError` and exiting the program.
* **Validation test**: Run batch mode, pass a bad column name, ensure it reprompts.
* **Owner suggestion**: Frontend / CLI Dev
* **ETA suggestion**: 24h

**[Tier 6] [Minor] [Findability, Usability] [No explicit Help command in interactive loop] [Code Review] [High]**
* **Fix**: Support "h" or "help" in the interactive prompt to explain what valid inputs look like (UUIDs, Share URLs) and how multi-file modes work.
* **Acceptance Criteria**: Typing `help` prints a short manual of valid input formats and explains the active `output_mode`.
* **Validation test**: Type `help` in the loop and verify the instructions appear without crashing or querying Iconik.
* **Owner suggestion**: CLI Dev
* **ETA suggestion**: 24h

**[Tier 6] [Minor] [Usability] [Lack of loading indicator for single lookups] [Code Review] [High]**
* **Fix**: Print a brief "Looking up..." message before hitting the API, or clear it upon success.
* **Acceptance Criteria**: In the interactive loop, after submitting a URL, the user receives immediate visual feedback that the network request is occurring.
* **Validation test**: Enter an asset ID, observe loading text before the box output appears.
* **Owner suggestion**: CLI Dev
* **ETA suggestion**: 24h

## 6. UX Honeycomb Scorecard

| Pillar | Score (1-7) | Justification |
| :--- | :--- | :--- |
| **Credible** | 7 | Uses standard Keychain for secrets; handles invalid API responses gracefully. |
| **Desirable** | 6 | Clean UI (`UI.box`, colors), much faster than manual clicking in the web app. |
| **Usable** | 5 | Fast and intuitive, but error recovery in some interactive prompts (column selection) is brittle. |
| **Valuable** | 7 | Saves immense time for operators doing bulk extractions. |
| **Findable** | N/A | CLI tool. |
| **Useful** | 7 | Solves the core problem with exactly the right output formats (S3, HTTPS). |
| **Accessible** | 6 | Text-based, readable, allows `--quiet` for screen-reader or scripting compatibility. |

## 7. User Journey Friction Map

1.  **Discover**: User runs script. (`Low friction`)
2.  **Onboarding (Auth)**: If no auth, prompts for App ID and Auth Token. Saves to Keychain. (`Low friction`)
3.  **Single Lookup**: User pastes URL -> wait 1-2s -> sees boxed output. (`Low friction`, but missing loading indicator)
4.  **Batch Lookup**: User passes CSV. Prompts for column. If typo, crashes. (`Medium friction`)
5.  **Recovery**: If asset offline, clearly states `OFFLINE`. (`Low friction`)

## 8. Accessibility Assessment
The CLI correctly uses standard standard out/err and colors can be turned off (or are disabled automatically when not in a TTY). Output relies on structure, making it easily parsable by screen readers or other scripts.

## 9. Research Snapshot
**Confidence:** High (Internal code analysis).
No external telemetry analyzed. Built on robust CLI paradigms.

## 10. Concrete Fixes

**Fix 1: Interactive Column Retry (dev/iconik_locator.py)**
Modify `choose_column` to loop on invalid input when prompting interactively:
```python
    while True:
        raw = ui.ask("Which column contains asset/share links or IDs? Enter index or name", suggested)
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(columns):
                return columns[idx]
        for col in columns:
            if col == raw or col.lower() == raw.lower():
                return col
        ui.err(f"Column not found: {raw}. Please try again.")
```

## 11. Research Gaps and Next Tests
- **Test:** Observe a user running a batch CSV for the first time to see if the column selection UI is immediately understood.

## 12. Release Checklist
- [ ] Implement retry loop for column selection.
- [ ] Add `help` command support in the interactive loop.
- [ ] Design Sign-off.

## 13. Progress Delta
*N/A - Initial Review*
