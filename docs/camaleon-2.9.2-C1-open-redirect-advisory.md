# Security Advisory (draft) — Open Redirect in Camaleon CMS `safe_redirect_url`

**Status:** DRAFT for coordinated disclosure to the maintainer
(`owen2345/camaleon-cms`). Not yet reported. Do not publish until the maintainer
has been given a fix window.

**Affected software:** Camaleon CMS (Ruby gem `camaleon_cms`)
**Version reviewed:** 2.9.2 (current `main` at time of review)
**Vulnerability class:** URL Redirection to Untrusted Site (Open Redirect) — CWE-601
**Reporter:** (fill in)
**Requires authentication:** No (pre-auth reachable via the login flow)

---

## Summary

`CamaleonCms::SessionHelper#safe_redirect_url` — the sanitizer intended to keep
the login `return_to` redirect on-site — can be bypassed with a **scheme-relative
URL that omits the `//` authority marker** (e.g. `https:/evil.com`). Ruby's
`URI.parse` reports a `nil` host for such inputs, so the sanitizer's off-host
check is skipped and the raw value is used as a redirect target. Rails'
`redirect_to` open-redirect protection shares the same `nil`-host blind spot and
does not block it either. A standards-compliant browser normalizes
`https:/evil.com` to `https://evil.com/`, navigating the victim off-site.

## Affected code

`app/helpers/camaleon_cms/session_helper.rb`

```ruby
def safe_redirect_url(url)
  return if url.blank?
  uri = URI.parse(url)
  return if uri.host.present? && uri.host != request.host   # <-- nil host => check skipped
  url
rescue URI::InvalidURIError
  nil
end
```

The function rejects a URL only when `URI.parse` yields a **non-blank host** that
differs from `request.host`. Inputs whose host parses to `nil`/empty pass through.

## Reachability

Pre-authentication, via the admin login `return_to` parameter:

- `app/controllers/camaleon_cms/admin/sessions_controller.rb:13` —
  `redirect_to(safe_redirect_url(params[:return_to]) || cama_admin_dashboard_path)`
- `sessions_controller.rb:15` stores `cookies[:return_to] = params[:return_to]`,
  later consumed at `session_helper.rb:30` via `safe_redirect_url`.
- Also `session_helper.rb:108`.

Attack URL: `https://victim.example/admin/login?return_to=https:/evil.com`
After the user authenticates (or immediately, if already signed in), they are
redirected to `https://evil.com/`.

## Proof of concept / validation

Validated locally (no third-party system involved) with Ruby 3.3.6 and the
project-pinned `actionpack 8.1.3.1`:

1. **Sanitizer bypass** — `safe_redirect_url("https:/evil.com")` returns
   `"https:/evil.com"` (because `URI.parse("https:/evil.com").host == nil`).
2. **Framework guard bypass** — driving the real `redirect_to("https:/evil.com")`
   through an `ActionController` on Rails 8.1.3.1 produces
   `HTTP 302, Location: https:/evil.com` with no `UnsafeRedirectError`.
3. **Client navigation** — a WHATWG-compliant URL parser normalizes
   `https:/evil.com` → `https://evil.com/` (verified with curl's
   `url_effective`; Chrome/Firefox/Safari apply the same special-scheme
   normalization).

Confirmed payloads: `https:/evil.com`, `https:///evil.com`.

> Recommend a final visual confirmation in a real browser before submission —
> the parser-level evidence is conclusive, but a screenshot of the off-site
> navigation strengthens the report.

## Impact

Open redirect from a trusted CMS login URL. Enables convincing phishing
(victim sees the real site's domain, lands on attacker content) and can be
abused to exfiltrate tokens in any flow that reflects `return_to` into an
authenticated redirect. Severity is low-to-moderate.

Suggested CVSS 3.1: `AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:N/A:N` → **6.1 (Medium)**
(same vector class as prior reflected-redirect/XSS CVEs; adjust after maintainer
review).

## Suggested fix

Harden `safe_redirect_url` to (a) enforce a scheme allowlist and (b) reject any
absolute form whose authority cannot be positively matched to the site host:

```ruby
def safe_redirect_url(url)
  return if url.blank?

  # Only same-origin relative paths, or absolute http(s) URLs to this exact host.
  return if url !~ %r{\A/(?!/)}  &&  # allow "/path" but not "//host" or "/\\host"
            begin
              uri = URI.parse(url)
              !(uri.is_a?(URI::HTTP) && uri.host.present? && uri.host == request.host)
            rescue URI::InvalidURIError
              true
            end
  url
end
```

Or reuse the existing, well-tested `UserUrlValidator` (already in the codebase)
in a "same-site only" mode. The key point: **treat a `nil`/blank parsed host as
untrusted, not as same-origin**, and reject scheme-bearing inputs that lack a
proper `//host` authority.

## Timeline

- YYYY-MM-DD — discovered via source review of 2.9.2
- YYYY-MM-DD — reported privately to maintainer (GitHub private advisory)
- (pending) — fix / CVE assignment / public disclosure

---

## Disclosure process (reminder)

1. Report privately first: repo → **Security → Report a vulnerability**
   (GitHub private vulnerability reporting) on `owen2345/camaleon-cms`.
2. Request a CVE via GitHub's advisory "Request CVE" once the maintainer
   confirms, or via MITRE `cveform.mitre.org` if unresponsive.
3. Add the advisory to `rubysec/ruby-advisory-db` after publication so
   `bundler-audit` picks it up.
