# Self-Healing & AI Fallback Engine

The self-healing engine handles locator lookup failures due to minor UI changes (e.g. text or label updates) and heals them on the fly.

## Healing Levels

### Level 1: Fuzzy Heuristic Matching (Offline)
When a step times out, md-e2e evaluated client-side visibility metrics, extracts candidates matching the role confinement (`TargetType`), and calculates similarity ratios using `difflib.SequenceMatcher`.

**Safeguards**:
- **Similarity Threshold**: Must be $\ge 0.70$.
- **Role Confinement**: Confinds BUTTON target types to `<button>`/`role="button"`, LINK target types to `<a>`/`role="link"`, etc.
- **Ambiguity Delta**: Top candidate score must exceed the second candidate's score by $\ge 0.12$.
- **Opposing Verb Guard**: Rejects matching opposite verbs (e.g., `Delete` $\leftrightarrow$ `Save`, `Confirm` $\leftrightarrow$ `Cancel`).
- **Negative Assertion Bypass**: Negative assertions like `ASSERT_HIDDEN` are never healed.

### Level 2: AI Fallback (Optional)
If Level 1 heuristics fail, the engine can route the DOM snippet and step details to a lightweight LLM (e.g., using `llm_api_key` config) to resolve the correct element.

## Local Caching
Healed selectors are cached in `.md_e2e_cache.json` using raw-template cache keys:
```json
{
  "Auth Suite::User Login::12::Sign In Button": "Log In"
}
```
If a cached healed selector fails subsequently, it is automatically invalidated (cache busted), and the healing pipeline is re-triggered.
