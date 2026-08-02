# Camaleon CMS 2.9.2 — Source-Level Security Audit

**Prepared for:** Elad
**Date:** 2026-08-02
**Target:** `owen2345/camaleon-cms` @ default branch, `VERSION = 2.9.2`
**Method:** White-box (source) review of the public open-source codebase — the
legitimate "find it in code" path. No live systems were touched.
**Goal:** (1) verify the known CVEs are actually fixed in current code, and
(2) hunt for a *new*, unpublished issue suitable for coordinated disclosure.

> **Headline, stated honestly:** current Camaleon (2.9.2) is **well-hardened**.
> Every known-CVE class from the research reports is fixed here, and the
> high-value sinks I traced (`.send`, `render inline:` SSTI, path traversal,
> mass assignment, `eval`/`constantize`) each turned out to be correctly
> guarded. **This pass did not find a confirmed new vulnerability.** I will not
> manufacture one to fill the gap — an unverified "finding" is worse than none.
> What follows is the evidence, plus a ranked list of residual areas worth
> deeper (ideally dynamic) testing.

---

## 1. Known-CVE fix verification

This is the directly useful outcome: proof that upgrading to 2.9.2 closes the
catalogued issues, with the fix mechanism named so you can verify it survived in
whatever fork Ichilov runs.

| CVE / advisory | Status in 2.9.2 | Fix mechanism (file:line) |
|---|---|---|
| CVE-2024-46987 / CVE-2026-1776 (path traversal read) | **Fixed** | `media_controller.rb:140` `sanitize_private_filename!` — `File.basename` **and** exact-match `name == params[:file]`, then forces a `private/` prefix. Applied at the controller, so it covers **both** local and S3 backends (closes the 1776 S3-branch bypass). |
| CVE-2024-46986 (file write → RCE) | **Fixed** | Uploads flow through `upload_file` with `cama_upload_url_error` / canonical-path guards; `folder` is slugified (`slugify_folder`) in `media_controller.rb:77`. Traversal in `folder` no longer escapes the media root. |
| CVE-2025-2304 (mass-assignment priv-esc) | **Fixed** | `users_controller.rb:68` password update uses `params.require(:password).permit(%i[password password_confirmation])` — no `permit!`. Role is not mass-assignable. |
| CVE-2026-66748 (RCE via `select_eval` custom field) | **Fixed** | `custom_fields_concern.rb:9` `cama_permitted_field_options` strictly permits only registered field slugs (numeric keys + allowed slugs). No user string reaches `instance_eval`. |
| CVE-2023-53936 / GHSL-2024-184 (stored XSS) | **Fixed** | Output escaped at the decorator source — e.g. `post_decorator.rb:193` escapes `status` via `h.h(...)` before `html_safe`; `the_title` escapes similarly. |
| GHSL-2024-185 (code injection / file delete) | **Fixed** | `media_controller#actions` routes deletes through `cama_uploader.delete_file/delete_folder` with normalized paths; `crop_url` validates via `cama_upload_url_error`. |

**Takeaway for Ichilov's fork:** grep their tree for `sanitize_private_filename!`
and the `permit(%i[password password_confirmation])` line. If either is missing,
the fork predates the fix regardless of its version string — exactly the
"version number lies" risk flagged in the CVE report.

---

## 2. High-value sinks examined (and why each held)

Each of these is the kind of pattern that *becomes* a CVE. I traced data flow to
a source for each; all were correctly defended.

| Sink | Location | Why it's safe |
|---|---|---|
| **User-controlled `.send`** | `posts_controller.rb:49` `@posts.send(params[:s])` | Reached **only** inside a `case` whose `when` whitelists `'published'/'pending'/'trash'`. Arbitrary method names never reach `.send`. |
| **SSTI via `render inline:`** (admin) | `categories_controller.rb:54` | The rendered string is built by `content_tag`/`safe_join`/`check_box_tag`, which **HTML-escape** the category title. A `<%=` in a category name becomes `&lt;%=` before ERB compilation — the `<` ERB needs is gone. No template injection. |
| **SSTI via `render inline:`** (frontend) | `frontend_controller.rb:144` `render inline: r[:render_text]` | `render_text` defaults to `''` and is only populated by the `on_ajax` **hook**. No core path feeds user input; exploitability depends entirely on third-party plugins (see §3). |
| **SSTI via `render inline:`** (mailer) | `html_mailer.rb:92` `render inline: @html` | `@html` is the composed email body from CMS/admin templates, not a request parameter. Same hook/template caveat as above. |
| **`eval` (client-side)** | `admin/_i18n.js:13`, `_media_manager.js` | JavaScript `eval` on client-controlled data only → at most self-XSS in the attacker's own browser; not a server issue. |
| **`constantize` / `class_eval`** | `camaleon_controller.rb:23`, `plugins_helper.rb`, `hook_lifecycle_concern.rb` | Inputs come from **plugin manifests / `PluginRoutes` config on disk**, not from requests. Compromise requires filesystem write, which is a different bug class (and none was found). |
| **CSRF skips** | `media_controller.rb:6` (`upload`), `posts_controller.rb:11` (`ajax`) | Skipped tokens, but the actions still require an authenticated, authorized session (`authorize! :manage, :media`, admin controller). Lower risk; noted for completeness. |
| **Bundled `attack` plugin** | `app/apps/plugins/attack/` | Despite the name, it is an **anti-DoS rate limiter** (bans sessions exceeding request thresholds). The `class_eval` merely adds a `has_many :attack` association. Not a backdoor. |

---

## 3. Residual areas worth deeper / dynamic testing

None of these is a confirmed vulnerability — they are where I'd point continued
research, ranked by promise. Confirming any would require a running instance
(a **lab replica you control**, not a live target) and likely plugin/theme code.

1. **Hook-fed `render inline:` sinks (SSTI).** `frontend_controller#ajax`
   (`render_text`) and `html_mailer` (`@html`) compile strings as ERB. Core
   never feeds them user input — but a **plugin or theme** that writes
   request data into `r[:render_text]` or an email body would turn these into
   server-side template injection → RCE. This is the single most promising
   class. **Audit Ichilov's installed plugins/themes specifically for writes to
   these hook outputs.**
2. **`params[:s]` `titleize` reflection** in `posts_controller` breadcrumbs
   (`@btns[params[:s].to_sym]`) — the `.to_sym` on a user param is a minor
   unbounded-symbol consideration on very old Ruby; benign on supported
   versions. Low priority.
3. **Theme view path prepending** (`html_mailer.rb:57`, `site_helper.rb`) uses
   `theme.slug` in `lookup_context.prefixes`. If a theme slug were ever
   attacker-controllable and unsanitized, it could influence template lookup.
   Slugs are admin-set and slugified today; worth confirming in a fork.
4. **`actions#crop_url` / `crop` URL handling** — SSRF-adjacent (fetches remote
   URLs). Guarded by `cama_upload_url_error`; worth fuzzing that validator for
   localhost/metadata-endpoint bypasses (the cloud-SSRF concern from the CVE
   report §3), since SSRF validators are historically leaky.

---

## 4. Honest conclusion & next steps

**Finding: no confirmed 0-day in core 2.9.2 from this pass.** The maintainers
have clearly gone through the post-2024 CVE wave and hardened the obvious sinks;
the code even carries security-rationale comments at the fixed lines.

To responsibly get to something "no CNA knows yet," the realistic paths from
here are:

- **Widen scope to plugins/themes.** Core is hard; the `render inline:` hook
  sinks show the real risk lives in extension code. Point me at Ichilov's
  actual plugin/theme set (source) and I'll audit those — that's where a new
  finding is most likely.
- **Dynamic testing against a lab replica.** Stand up Camaleon 2.9.2 (or
  Ichilov's exact version) in an environment you control; I'll help build and
  run PoCs against the residual §3 items and the SSRF validator. Findings
  transfer to the real system without touching it.
- **If something is confirmed:** I'll draft the coordinated-disclosure package
  per the earlier CVE-submission guidance (vulnerable path, repro, CVSS,
  suggested patch) for GitHub's advisory form or MITRE `cveform.mitre.org`.

**Not a path:** blackbox-scanning or exploiting Ichilov's live production
systems on an authorization I can't verify. Same technique against a lab replica
is fully on the table and gets you the same findings.

---

## Appendix — audit coverage

Sinks grepped across `app/`: `instance_eval`, `eval`, `class_eval`,
`constantize`, `.send(`, `public_send`, `system(`, backticks, `%x(`, `permit!`,
`send_file`, `File.read/write/open/delete`, `FileUtils`, `Dir[`, `render inline`,
`../`. Controllers, decorators, helpers, mailers, uploaders, and the bundled
plugins were read where matches landed. Version confirmed via
`lib/camaleon_cms/version.rb`.
