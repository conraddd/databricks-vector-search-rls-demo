"""Generate synthetic emails for the Vector Search RLS demo.

Each row is assigned an `acl_email` drawn from OWNER_EMAILS. The deployed MCP
server filters search results to rows whose `acl_email` matches the calling
user's Databricks identity (OBO) -- that filter is the row-level security.

Re-run this any time you change OWNER_EMAILS or NUM_EMAILS, then re-load the
table and let the Delta-Sync index pick up the changes.

Usage:
    python setup/generate_emails.py --out /tmp/emails.csv
"""

import argparse
import csv
import random

# ---------------------------------------------------------------------------
# CONFIG -- edit these. OWNER_EMAILS must be REAL Databricks identities that
# will call the agent (OBO), otherwise their filtered searches return nothing.
# ---------------------------------------------------------------------------
OWNER_EMAILS = [
    "conrad.ho@databricks.com",
    "ray.liew@databricks.com",
]
NUM_EMAILS = 300
SEED = 42

# Distinct topic clusters so semantic search is meaningful AND you can show
# each owner returning different rows for the same query.
TOPICS = {
    "quarterly budget": [
        "Q{q} budget review for the {team} team",
        "Please find attached the {team} spend forecast for Q{q}. We are tracking "
        "${amt}K against plan, with the largest variance in cloud infrastructure. "
        "Let's align on reallocations before the finance close.",
    ],
    "customer escalation": [
        "Escalation: {cust} production outage",
        "{cust} hit a Sev-1 this morning impacting their data pipelines. The "
        "account team needs an RCA and a remediation timeline by EOD. Looping in "
        "support and the field engineer for {cust}.",
    ],
    "hiring": [
        "Hiring update: {team} headcount",
        "We have two approved reqs for the {team} team. I've moved three candidates "
        "to onsite and need interviewers for next week. Please grab a slot on the "
        "panel for the senior role.",
    ],
    "product launch": [
        "Launch readiness: {feature}",
        "The {feature} GA is on track for next month. Docs and the demo are nearly "
        "done; we still need the pricing page and a final security sign-off before "
        "we announce.",
    ],
    "security review": [
        "Security review for {feature}",
        "The security team flagged a few findings on {feature}: secrets handling and "
        "an over-broad IAM role. None are blockers but we should remediate before "
        "GA. Threat model attached.",
    ],
    "contract negotiation": [
        "{cust} renewal terms",
        "{cust} is pushing for a 15% discount on their multi-year renewal in "
        "exchange for a larger committed spend. Legal has redlined the MSA. Need "
        "your approval on the floor price.",
    ],
    "travel": [
        "Travel plans for the {cust} onsite",
        "Booked flights for the {cust} onsite next week. Agenda covers the "
        "architecture review and an exec readout. Let me know if you want to add a "
        "working session on the migration.",
    ],
}

PEOPLE = [
    "alex.kim@example.com", "priya.nair@example.com", "sam.ortiz@example.com",
    "lena.fischer@example.com", "marcus.li@example.com", "dana.cole@example.com",
]
TEAMS = ["platform", "analytics", "field engineering", "sales", "ml", "security"]
CUSTOMERS = ["Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries"]
FEATURES = ["Vector Search RLS", "Lakebase autoscaling", "Genie spaces", "Model Serving v2"]


def generate(out_path: str) -> int:
    rnd = random.Random(SEED)
    rows = []
    topic_names = list(TOPICS.keys())
    for i in range(NUM_EMAILS):
        owner = OWNER_EMAILS[i % len(OWNER_EMAILS)]  # round-robin ownership
        topic = topic_names[i % len(topic_names)]
        subj_tmpl, body_tmpl = TOPICS[topic]
        fills = dict(
            q=rnd.randint(1, 4), team=rnd.choice(TEAMS), amt=rnd.randint(50, 900),
            cust=rnd.choice(CUSTOMERS), feature=rnd.choice(FEATURES),
        )
        rows.append({
            "id": f"msg-{i:04d}",
            "sender": rnd.choice(PEOPLE),
            "recipient": owner,  # the owner "received" it -> plausible ACL story
            "subject": subj_tmpl.format(**fills),
            "body": body_tmpl.format(**fills),
            "topic": topic,
            "acl_email": owner,
        })

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "sender", "recipient", "subject", "body", "topic", "acl_email"]
        )
        writer.writeheader()
        writer.writerows(rows)

    # Print a per-owner breakdown so you can sanity-check the A/B split.
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
    args = ap.parse_args()
    generate(args.out)
