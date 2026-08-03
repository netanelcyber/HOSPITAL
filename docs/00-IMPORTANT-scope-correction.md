# ⚠️ SCOPE CORRECTION — READ FIRST

**Date:** 2026-08-02

## The documents in this folder are about the WRONG system

All the other files in `docs/` — the CVE reports, the detection playbook, the
2.9.2 source audit, and the confirmed C-1 open redirect — analyze the
**open-source Camaleon CMS**: the Ruby-on-Rails gem `camaleon_cms`
(`owen2345/camaleon-cms`, vendor "tuzitio"). It is a generic, public web CMS.

**The actual intended target is a different product:** the proprietary
**"Chameleon" (קמיליון) system by Elad Systems (אלעד מערכות)** — a closed-source
Israeli product. It shares only the transliterated *name* with the open-source
CMS. There is no established relationship between the two codebases.

## What this means

- **None of the findings in the other docs apply to Elad Systems' Chameleon.**
  The CVEs, the audit, and the C-1 open redirect are properties of the
  open-source Ruby CMS and say nothing about Elad's proprietary product.
- **The C-1 open redirect finding is still real and valid** — but only against
  open-source Camaleon CMS 2.9.2. It remains worth reporting upstream to
  `owen2345/camaleon-cms` on its own merits. It is simply unrelated to Elad.
- There is **no public CVE record** located for Elad Systems' Chameleon, and no
  first-party information about its internals was available for this work.

## What would be needed to analyze the real target

Legitimate, verifiable access to the product itself — not the live deployment:

1. **Source code or a dependency manifest** for Elad Systems' Chameleon,
   obtained through an authorized channel (i.e. provided by Elad Systems or by
   Ichilov under a contract that permits it). With that, a real source-level
   audit is possible.
2. A **written authorization / rules-of-engagement** from the system owner if
   any dynamic testing is ever contemplated.

## What is NOT a path

Active/dynamic security testing of Elad's Chameleon **as deployed in production
at a live hospital (Ichilov / Tel Aviv Sourasky)** on the basis of an
authorization that cannot be verified here. That line was held throughout this
work and continues to apply.

## Status of the existing docs

They are retained as a **methodology demonstration** — how to research a CMS's
CVE history, verify fixes in source, and validate a candidate finding in a
sandbox without touching any live system. They are accurate *for the
open-source Camaleon CMS*. They should not be read as findings about Elad
Systems' product.
