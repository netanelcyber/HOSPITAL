# Camaleon CMS 2.9.2 — Candidate Findings (unconfirmed)

**Prepared for:** Elad
**Date:** 2026-08-02
**Companion to:** [`camaleon-2.9.2-source-audit.md`](./camaleon-2.9.2-source-audit.md)
**Confidence legend:** 🟠 candidate (plausible, needs dynamic validation) ·
🔵 examined → safe · ⚪ requires precondition outside request scope

> **These are NOT confirmed vulnerabilities.** They are the output of static
> hypothesis generation, ranked and — importantly — *including the ones that
> did not survive scrutiny*, so the reasoning is auditable. Nothing here should
> be reported to a CNA or the maintainer until it is reproduced on a running
> instance. Treating a 🟠 as a finding would be exactly the fabrication I've
> been refusing to do. Each item states precisely what would confirm or kill it.

---

## ✅ C-1 — Open redirect in `safe_redirect_url` (CWE-601) — **CONFIRMED**

> **Status update (validated in local sandbox, no live target):** promoted from
> 🟠 candidate to ✅ **confirmed**. All three layers were proven with Ruby 3.3.6
> and the project-pinned Rails 8.1.3.1. See "Validation results" below. A
> disclosure-ready write-up is in
> [`camaleon-2.9.2-C1-open-redirect-advisory.md`](./camaleon-2.9.2-C1-open-redirect-advisory.md).

### Validation results

| Layer | Test | Result |
|---|---|---|
| 1. Camaleon guard | `safe_redirect_url("https:/evil.com")` (exact repro) | **Passes** — returns the string; `URI.parse` host is `nil`, so the off-host check is skipped |
| 2. Rails guard | real `redirect_to` on actionpack **8.1.3.1** | **Passes** — emits `Location: https:/evil.com`, HTTP 302, **no** `UnsafeRedirectError` (Rails allows it because `URI(url).host` is `nil`) |
| 3. Client | WHATWG URL normalization (curl; same as Chrome/Firefox/Safari for special schemes) | **Navigates off-site** — `https:/evil.com` → `https://evil.com/` |

Working payloads: `https:/evil.com` and `https:///evil.com`. (`https:evil.com`
stays opaque and is **not** a reliable vector; `javascript:`/`data:` are passed by
Camaleon but browsers don't execute them from a `Location` header.)

My earlier ~30% estimate assumed Rails' `allow_other_host` would blunt this. It
does **not** — the `nil`-host case defeats both Camaleon's and Rails' checks. The
two guards share the same blind spot.



**Location:** `app/helpers/camaleon_cms/session_helper.rb:177`
**Reachability:** pre-auth. `GET /admin/login?return_to=<payload>` → the value is
stored in `cookies[:return_to]` (`sessions_controller.rb:15`) and used in a
`redirect_to` after login (`session_helper.rb:30`, `:108`, `:13`).

```ruby
def safe_redirect_url(url)
  return if url.blank?
  uri = URI.parse(url)
  return if uri.host.present? && uri.host != request.host
  url
rescue URI::InvalidURIError
  nil
end
```

**The hypothesis.** The guard only rejects a URL when `URI.parse` yields a
*non-blank host that differs from `request.host`*. Several inputs a browser will
navigate off-site produce a **blank `uri.host`** under Ruby's `URI.parse`, so the
guard passes them through:

| Payload | `URI.parse(..).host` | Browser interpretation |
|---|---|---|
| `https:/evil.com` (single slash) | `nil` (parsed as path `/evil.com`) | Chrome normalizes → `https://evil.com/` — **off-site** |
| `https:evil.com` | `nil` | some browsers → `https://evil.com` |
| `javascript:alert(document.domain)` | `nil` (opaque) | ignored in `Location:` by modern browsers (no XSS) — low impact |
| `//evil.com` (protocol-relative) | `evil.com` → **correctly rejected** | — |
| `/\evil.com` (backslash) | raises `InvalidURIError` → **nil, rejected** | — |

So the protocol-relative and backslash classics are *already handled* (host
detected, or parse raises). The residual candidate is the **single-slash scheme
form** (`https:/evil.com`), where Ruby sees a path but the browser reconstructs
an authority.

**What makes this UNCONFIRMED (and possibly a non-issue).** Rails 7+ `redirect_to`
has its own `allow_other_host` protection that raises `UnsafeRedirectError` for
external redirects. Whether `https:/evil.com` slips past *both* Ruby's `URI` and
Rails' internal host check is the crux — it may well be caught by the second
layer. There is **no scheme allowlist** here, which is a real weakness, but the
exploitable-impact question depends on the Rails version and browser.

**To confirm or kill (dynamic test on a lab replica):**
1. `curl -si "http://<lab>/admin/login?return_to=https:/evil.com"`, log in, and
   inspect the resulting `Location:` header. If it emits `https:/evil.com`
   without a `UnsafeRedirectError`, test in Chrome/Firefox to see if it navigates
   off-site.
2. Repeat for `https:evil.com`, `/%2f%2fevil.com`, `https:/\evil.com`,
   `https:/%5Cevil.com`, and a leading-control-char form `\thttps://evil.com`.
3. If any redirects off-site → confirmed CWE-601 (low–moderate; phishing/oauth-token
   theft vector). **Suggested fix:** enforce a scheme allowlist (`http`/`https`
   only) *and* require the result to be a relative path or an absolute URL whose
   parsed host equals `request.host`, rejecting scheme-with-no-`//` forms.

**Honest confidence:** ~30%. Real code smell (no scheme allowlist, parse-vs-browser
divergence), but Rails' own guard likely blunts impact. Worth 20 minutes on a lab.

---

## 🔵 C-2 — Theme view-path prefix from `params[:controller]` → **safe**

**Location:** `app/controllers/camaleon_cms/apps/themes_front_controller.rb:13`
(and the plugin equivalents).

```ruby
theme_name = params[:controller].split('/')[1]
return render_error(404) unless current_theme.slug == theme_name
lookup_context.prefixes.prepend(params[:controller].sub("themes/#{theme_name}", "themes/#{theme_name}/views"))
```

**Initial hypothesis:** attacker-controlled `params[:controller]` containing `../`
poisons the ERB template lookup path → LFI / arbitrary template render → RCE.

**Why it's safe.** Theme/plugin routes are generated in `lib/plugin_routes.rb` as
**static** `namespace :themes do namespace '<key>' do <routes_admin.txt> end end`
blocks. `params[:controller]` is therefore the *route-matched* controller string
(`themes/<key>/<action>`), not free-form URL input — Rails does not let an
attacker inject `../` into it. The `theme_name` is additionally pinned to
`current_theme.slug`. No traversal reaches `prefixes.prepend`. **Killed.**

---

## ⚪ C-3 — Plugin/theme route `.txt` executed as route DSL

**Location:** `lib/plugin_routes.rb:92,106,133,147` — each enabled plugin/theme's
`config/routes_<env>.txt` is `File.read` and concatenated into a string that is
evaluated as Rails routing DSL.

**Assessment:** this is code execution by design, but the input is a **file on
disk inside an installed plugin/theme**, not a request parameter. Reaching it
requires the ability to write a plugin's files — i.e. admin-level plugin
installation or a *separate* file-write primitive (none found; the upload path
is hardened per the main audit). Real risk only in a **supply-chain** scenario:
a malicious third-party theme/plugin ships a hostile `routes_*.txt`. Relevant to
the dependency-review offer, not a request-time core bug.

**Recommendation:** vet third-party themes/plugins before install; the route txt
is an under-appreciated code-execution surface in that trust decision.

---

## 🔵/⚪ C-4 — Anonymous comment `author_url` has no scheme allowlist → latent theme XSS

**Location:** `frontend_concern.rb:62` stores `post_comment[:url]` verbatim as
`author_url`; `post_comment_decorator.rb:36 the_author_url` returns it unfiltered.

**Assessment.** Comment **content** is safe in shipped code: the default theme
renders `<%= comment.content %>` (`_comments_list.html.erb:14`), and ERB
auto-escapes — so the old unauth comment-XSS class (CVE-2021-25969) stays closed.
`author_url`, however, is stored with **no scheme validation** (a
`javascript:`/`data:` value is accepted). The default theme does **not** render
`the_author_url` in an `href`, so it is **not exploitable as shipped** (🔵). But
any theme that does `<a href="<%= comment.the_author_url %>">` would have XSS,
because HTML-escaping does not neutralize a `javascript:` scheme (no angle
brackets to escape). This is a latent **theme footgun** (⚪), not a core bug.

**Cheap hardening:** validate `author_url` scheme (`http`/`https` only) at save
time in `save_comment`, so no theme can turn it into a sink. Low effort, removes
a whole latent class.

## Summary

| ID | Class | Confidence | Status |
|---|---|---|---|
| C-1 | Open redirect (CWE-601) | 🟠 ~30% | Needs dynamic test (§C-1 steps) |
| C-2 | Template-path LFI | 🔵 killed | Route-constrained, safe |
| C-3 | Route-DSL execution | ⚪ | Requires plugin file write (supply-chain) |
| C-4 | Comment `author_url` XSS | 🔵/⚪ | Safe as shipped; latent theme footgun |

**Net:** one worth-testing candidate (C-1, an open redirect with real code smell
but likely blunted by Rails' own guard), one killed, one supply-chain note. This
is consistent with the main audit's conclusion — **no confirmed core 0-day**, and
the most credible residual is a low-severity redirect, not the critical bug the
target-focused requests were reaching for.

**Next step to raise confidence on C-1:** a lab replica (2.9.2, or Ichilov's exact
version). I'll run the §C-1 test matrix and either confirm it into a
disclosure-ready write-up or kill it. That is the honest path from "candidate" to
"CVE."
