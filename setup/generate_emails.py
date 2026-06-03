"""Generate a small, curated set of synthetic emails for the Vector Search RLS demo.

Each owner gets one email per THEME, so every theme has a matching pair (one per
owner). A query on a theme therefore returns BOTH owners' emails on the native Vector
Search MCP server (no RLS), but only the caller's email on the RLS-enabled server --
making the difference obvious. Several themes are deliberately sensitive (compensation,
reorg) so the cross-user leak on the native server is striking.

The deployed MCP server filters search results to rows whose `acl_email` matches the
calling user's Databricks identity (OBO) -- that filter is the row-level security.

Owners are provided at runtime (not hard-coded): pass --owners or set DEMO_OWNER_EMAILS.
They MUST be real Databricks identities that will call the agent (OBO), otherwise their
filtered searches return nothing. Personas are generic and assigned to owners by
position; each recipient's first name is derived from their email address.

Usage:
    python setup/generate_emails.py \\
        --owners "alice@yourco.com,bob@yourco.com" --out /tmp/emails.csv
    # or: export DEMO_OWNER_EMAILS="alice@yourco.com,bob@yourco.com"
"""

import argparse
import csv
import os

# Placeholder defaults -- override with --owners or DEMO_OWNER_EMAILS.
DEFAULT_OWNER_EMAILS = ["alice@example.com", "bob@example.com"]

# Generic persona profiles, assigned to owners by position (profile[i] -> owner[i],
# cycling if there are more owners than profiles). Not tied to any real person.
PERSONA_PROFILES = [
    {
        "team": "Platform", "customer": "Acme Corp", "system": "Ingestion API",
        "feature": "Vector Search RLS", "salary": 210, "bonus": 15, "equity": 1200,
        "discount": 12, "commit": 800, "roles": 18, "open": 3, "cut": 2,
    },
    {
        "team": "Field Sales", "customer": "Globex", "system": "Billing Service",
        "feature": "Lakebase Autoscaling", "salary": 195, "bonus": 20, "equity": 900,
        "discount": 18, "commit": 1200, "roles": 11, "open": 2, "cut": 4,
    },
    {
        "team": "Analytics", "customer": "Initech", "system": "Core Service",
        "feature": "Genie Spaces", "salary": 205, "bonus": 18, "equity": 1100,
        "discount": 15, "commit": 950, "roles": 14, "open": 2, "cut": 3,
    },
]

# Each theme: (topic, sender, subject template, body template).
THEMES = [
    (
        "compensation review", "people-ops@example.com",
        "Confidential: {first}'s H1 compensation review",
        "Hi {first}, your H1 compensation review is final: base ${salary}K, a {bonus}% "
        "target bonus, and an equity refresh of {equity} units. Please keep this "
        "confidential and do not forward.",
    ),
    (
        "customer renewal pricing", "legal@example.com",
        "{customer} renewal - pricing floor",
        "{first}, for the {customer} renewal we can go to a {discount}% discount against a "
        "${commit}K commitment. Legal has the redlined MSA. Do not share the floor price "
        "externally.",
    ),
    (
        "reorg and headcount", "hrbp@example.com",
        "Confidential: {team} reorg and headcount",
        "{first}, the {team} reorg affects {roles} roles - {open} new reqs and {cut} "
        "positions consolidated. Hold this until the all-hands; it is not yet public.",
    ),
    (
        "security incident", "secops@example.com",
        "Sev-1: {system} incident postmortem",
        "{first}, the {system} incident exposed a data-handling gap. The RCA is attached "
        "with remediation owners and timelines. Restricted distribution only.",
    ),
    (
        "product roadmap", "product@example.com",
        "Roadmap: {feature} GA plan",
        "{first}, the {feature} GA is targeted for next quarter. Pricing and the launch "
        "blog are still in draft - internal only until we announce.",
    ),
]


def _first_name(email: str) -> str:
    """Derive a display first name from an email local-part (alice.smith@x -> Alice)."""
    local = email.split("@", 1)[0]
    first = local.split(".")[0]
    return first.capitalize() if first else "There"


def generate(out_path: str, owner_emails: list) -> int:
    rows = []
    for oi, owner in enumerate(owner_emails):
        persona = {"first": _first_name(owner), **PERSONA_PROFILES[oi % len(PERSONA_PROFILES)]}
        for ti, (topic, sender, subj_tmpl, body_tmpl) in enumerate(THEMES):
            rows.append({
                "id": f"msg-{oi}-{ti}",
                "sender": sender,
                "recipient": owner,
                "subject": subj_tmpl.format(**persona),
                "body": body_tmpl.format(**persona),
                "topic": topic,
                "acl_email": owner,
            })

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "sender", "recipient", "subject", "body", "topic", "acl_email"]
        )
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for r in rows:
        counts[r["acl_email"]] = counts.get(r["acl_email"], 0) + 1
    print(f"Wrote {len(rows)} emails to {out_path}")
    for owner, n in counts.items():
        print(f"  {owner}: {n} rows")
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/emails.csv")
    ap.add_argument(
        "--owners",
        default=os.environ.get("DEMO_OWNER_EMAILS", ""),
        help="Comma-separated owner emails (real Databricks identities). "
        "Falls back to the DEMO_OWNER_EMAILS env var, then placeholder defaults.",
    )
    args = ap.parse_args()
    owners = [e.strip() for e in args.owners.split(",") if e.strip()] or DEFAULT_OWNER_EMAILS
    generate(args.out, owners)
