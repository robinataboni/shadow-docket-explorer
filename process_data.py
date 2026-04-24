import json, os, re
import pandas as pd

EXCEL_PATH = "shadow_docket_database_v2-0.xlsx"
OUTPUT_PATH = "shadow_docket_data.json"
HTML_PATH   = "index.html"

print("Reading Excel file (this may take a minute)...")
df = pd.read_excel(EXCEL_PATH, engine="openpyxl")
print(f"Loaded {len(df):,} rows")

# ── Presidential year (for emergency) ────────────────────────────────────────
df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
df["presidential_year"] = df["date_parsed"].apply(
    lambda d: d.year if pd.notna(d) and (d.month, d.day) >= (1, 20)
              else (d.year - 1 if pd.notna(d) else None)
)

# ── Orders: aggregate by Supreme Court term ───────────────────────────────────
orders_df = df.dropna(subset=["term"]).copy()
orders_df["term"] = orders_df["term"].astype(int)
orders_terms = sorted(orders_df["term"].unique().tolist())


def counts_by_term(frame, years):
    s = frame.groupby("term").size()
    return {str(y): int(s.get(y, 0)) for y in years}


def relief_by_term(frame, years):
    result = {}
    for rv in ["Granted", "Denied", "Dismissed", "Granted/Denied", "Missing"]:
        sub = frame[frame["relief"] == rv]
        if len(sub):
            result[rv] = counts_by_term(sub, years)
    return result


all_action_classes = sorted(orders_df["action_class"].dropna().unique().tolist())

orders_types = {}
orders_types["All Action Classes"] = {
    "total": counts_by_term(orders_df, orders_terms),
    "breakdowns": {"Relief": relief_by_term(orders_df, orders_terms)},
}
for ac in all_action_classes:
    ac_df = orders_df[orders_df["action_class"] == ac]
    entry = {
        "total": counts_by_term(ac_df, orders_terms),
        "breakdowns": {"Relief": relief_by_term(ac_df, orders_terms)},
    }
    if ac == "Certiorari":
        cert_bd = {}
        cert_df = ac_df[ac_df["cert_type"].notna()]
        for ct in ["IFP", "Paid"]:
            sub = cert_df[cert_df["cert_type"] == ct]
            if len(sub):
                cert_bd[ct] = counts_by_term(sub, orders_terms)
        entry["breakdowns"]["Petitioner Type"] = cert_bd
    orders_types[ac] = entry

orders_metric = {
    "label": "Total Orders",
    "has_types": True,
    "time_label": "Supreme Court Term",
    "years": [str(y) for y in orders_terms],
    "types": orders_types,
}

# ── Emergency: aggregate by presidential year (2003+) ─────────────────────────
emerg_df = df[
    (df["emergency_application"] == 1) &
    (df["presidential_year"].notna()) &
    (df["presidential_year"] >= 2003)
].copy()
emerg_df["presidential_year"] = emerg_df["presidential_year"].astype(int)
emerg_years = sorted(emerg_df["presidential_year"].unique().tolist())


def counts_by_pres_year(frame, years):
    s = frame.groupby("presidential_year").size()
    return {str(y): int(s.get(y, 0)) for y in years}


def relief_by_pres_year(frame, years):
    result = {}
    for rv in ["Granted", "Denied", "Dismissed", "Granted/Denied", "Missing"]:
        sub = frame[frame["relief"] == rv]
        if len(sub):
            result[rv] = counts_by_pres_year(sub, years)
    return result


def petitioner_type_breakdown(frame, years):
    def classify(row):
        if row.get("death_penalty") == 1:
            return "Death Penalty"
        if row.get("gov_petitioner") in (1, True):
            return "U.S. Government"
        return "Other"
    labels = frame.apply(classify, axis=1)
    result = {}
    for cat in ["Death Penalty", "U.S. Government", "Other"]:
        sub = frame[labels == cat]
        if len(sub):
            result[cat] = counts_by_pres_year(sub, years)
    return result


app_type_breakdown = {
    "Stay":       counts_by_pres_year(emerg_df[emerg_df["action_class"] == "Stay"], emerg_years),
    "Injunction": counts_by_pres_year(emerg_df[emerg_df["action_class"] == "Injunction"], emerg_years),
    "Vacate":     counts_by_pres_year(emerg_df[emerg_df["action_class"].isin(["Vacate", "Vacate Stay"])], emerg_years),
}

emergency_metric = {
    "label": "Emergency Applications",
    "has_types": False,
    "time_label": "Presidential Year",
    "years": [str(y) for y in emerg_years],
    "total": counts_by_pres_year(emerg_df, emerg_years),
    "breakdowns": {
        "Petitioner Type":  petitioner_type_breakdown(emerg_df, emerg_years),
        "Application Type": app_type_breakdown,
    },
}

# ── Write JSON ────────────────────────────────────────────────────────────────
output = {
    "metrics": {
        "orders":    orders_metric,
        "emergency": emergency_metric,
    },
}

json_str = json.dumps(output, separators=(",", ":"))
with open(OUTPUT_PATH, "w") as f:
    f.write(json_str)
print(f"Wrote {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH)/1024:.1f} KB)")

# ── Inject into index.html ────────────────────────────────────────────────────
if os.path.exists(HTML_PATH):
    with open(HTML_PATH, "r") as f:
        html = f.read()
    inline = f'<script id="inline-data">window.SHADOW_DATA={json_str};</script>'
    if '<script id="inline-data">' in html:
        html = re.sub(r'<script id="inline-data">.*?</script>', inline, html, flags=re.DOTALL)
    else:
        html = html.replace("</head>", inline + "\n</head>", 1)
    with open(HTML_PATH, "w") as f:
        f.write(html)
    print(f"Injected data into {HTML_PATH}")
