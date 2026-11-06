"""Hand-written dev and held-out test sets in the harness format.

Every expected value was checked against the snapshot pages (see DESIGN.md for the trace).
`dev_eval.jsonl` is used while iterating; `dev_test.jsonl` is held out and scored only at milestones.
Groups tie rewordings together so paraphrase consistency is measured."""
import json
from pathlib import Path

DEV, TEST = [], []


def q(split, id_, question, must, must_not=(), cat="current_value", group=None, as_of=None, src=(), w=1.5, exp=""):
    (DEV if split == "dev" else TEST).append({
        "id": id_, "question": question, "as_of": as_of, "expected_answer": exp, "must_include": list(must),
        "must_not_include": list(must_not), "category": cat, "weight": w, "expected_sources": list(src),
        "group": group or id_})


# --- rewordings of public items (same facts, new phrasing) ------------------------------------
q("dev", "r001a", "How much does the 17 month certificate special yield?", ["4.10%"], ["3.95%", "3.85%"], "tier_disambiguation", "g001")
q("dev", "r001b", "What's the APY on the seventeen-month CD special?", ["4.10%"], ["3.95%"], "tier_disambiguation", "g001")
q("test", "r001c", "17-month special share certificate rate?", ["4.10%"], ["3.95%"], "tier_disambiguation", "g001")
q("dev", "r009a", "What's the current 30-year fixed mortgage rate?", ["7.13", "7.25"], ["6.037%", "6.061%", "5.954%", "6.375%"], "stale_trap", "g009", src=["https://www.dupaco.com/personal/loans/home-loans"])
q("test", "r009b", "30 yr mortgage interest rate today?", ["7.13", "7.25"], ["6.037%", "6.061%", "5.954%"], "stale_trap", "g009")
q("dev", "r016a", "What APR would I get on a 5-year car loan for a 2025 vehicle?", ["5.39%"], ["5.34%", "5.19%"], "stale_trap", "g016", src=["https://www.dupaco.com/personal/loans/auto-motorcycle-loans"])
q("test", "r016b", "Auto loan rate for 60 months on a 2026 model year car?", ["5.39%"], ["5.34%"], "stale_trap", "g016")
q("dev", "r017a", "What's the rate on an 84 month auto loan for a 2024 car?", ["5.59%"], ["5.54%", "5.39%"], "stale_trap", "g017")
q("dev", "r034a", "Which credit cards does Dupaco offer, and what are the APRs?", ["Platinum Visa", "Rewards Visa", "Business Platinum", "Business Rewards", "12.5", "20.5"], ["9.9%"], "list_completeness", "g034")
q("test", "r034b", "List all of your Visa credit cards with their interest rates.", ["Platinum Visa", "Rewards Visa", "12.5", "15.5"], ["9.9%"], "list_completeness", "g034")
q("dev", "r045a", "What's the Share Savings rate for a $15,000 balance?", ["0.15"], ["0.30%", "0.40%"], "tier_disambiguation", "g045")
q("test", "r045b", "If I keep $12,000 in Share Savings, what dividend rate do I get?", ["0.15"], ["0.30%", "0.40%"], "tier_disambiguation", "g045")
q("dev", "r054a", "What routing number should I give my employer for direct deposit?", ["273974581"], ["271176899"], "entity_attribution", "g054")
q("test", "r054b", "Dupaco ABA number?", ["273974581"], ["271176899"], "entity_attribution", "g054")
q("dev", "r064a", "When are your branch lobbies open?", ["8:30"], ["ZIP code"], "branch_info", "g064")
q("dev", "r066a", "What hours is the drive-thru open?", ["8 a.m.", "6 p.m."], [], "branch_info", "g066")
q("test", "r066b", "Drive up window hours?", ["8 a.m.", "6 p.m."], [], "branch_info", "g066")
q("dev", "r068a", "Where is the Galena branch located?", ["11375 Oldenburg", "61036"], ["unable to find"], "branch_info", "g068")
q("dev", "r073a", "How many branch locations does Dupaco operate?", ["22"], ["24 branch", "23 branch"], "conflict_resolution", "g073")
q("test", "r073b", "What's the total number of Dupaco branches?", ["22"], ["24 branch"], "conflict_resolution", "g073")
q("dev", "r074a", "What date did the Hy-Vee branch close?", ["March 31, 2026"], ["don't have that detail"], "temporal_as_of", "g074")
q("dev", "r087a", "Has Forbes ranked Dupaco as a top credit union?", ["fifth"], ["fourth", "2020", "2021"], "stale_trap", "g087")
q("dev", "r008a", "Where can I find certificate rates online?", ["dupaco.com/personal/savings-account"], ["info.dupaco.com"], "stale_trap", "g008")
q("dev", "r052a", "What interest rate do your checking accounts pay?", ["2.50%"], ["3% APY"], "current_value", "g052")
q("test", "r052b", "How much does 1st Rate Checking earn?", ["2.50%"], ["3% APY"], "current_value", "g052")
q("dev", "r035a", "What is the regular APR on the Platinum Visa card?", ["12.5"], ["9.9%"], "tier_disambiguation", "g035")
q("dev", "r050a", "What's the APY on the Bright Savings online account?", ["2.25"], ["Jump Start", "0.35%"], "entity_attribution", "g050")
q("dev", "r028a", "36 month personal loan APR?", ["10.49"], [], "tier_disambiguation", "g028")
q("test", "r028b", "What rate do you charge for a three-year personal loan?", ["10.49"], [], "tier_disambiguation", "g028")
q("dev", "r046a", "What's the best APY I can get on Share Savings?", ["0.20", "25,000"], ["0.35%"], "tier_disambiguation", "g046")
q("dev", "r081a", "Who can become a member of Dupaco?", ["Iowa", "Illinois", "Wisconsin"], [], "conflict_resolution", "g081")
q("test", "r081b", "Am I eligible to join Dupaco?", ["Iowa", "Illinois", "Wisconsin"], [], "conflict_resolution", "g081")
q("dev", "r082a", "Where do I apply for membership online?", ["join.dupaco.com"], ["info.dupaco.com"], "stale_trap", "g082")
q("dev", "r080a", "Link to find a Dupaco branch or ATM?", ["dupaco.com/contact"], ["/locations/branch-hours"], "stale_trap", "g080")
q("dev", "r031a", "Tell me about the Home$tart grant.", ["15,000"], [], "current_value", "g031")
q("dev", "r094a", "Does Dupaco support Apple Pay?", ["Apple Pay"], [], "list_completeness", "g094")
q("dev", "r076a", "The Hy-Vee branch closed — which branches should its members use now?", ["Key West", "Sycamore"], ["CO-OP Shared Branch"], "branch_info", "g076")
q("dev", "r088a", "How many employees took Volunteer Time Off?", ["294"], [], "temporal_as_of", "g088")
q("dev", "r101a", "Do you offer student loans?", ["student loan"], ["Share Savings", "0.20%"], "entity_attribution", "g101")

# --- refusals -------------------------------------------------------------------------------
q("dev", "x01", "What's the current rate on a 5/1 ARM?", [], [], "should_refuse", w=2.0)
q("dev", "x02", "What APR do you offer on FHA loans?", [], [], "should_refuse", w=2.0)
q("dev", "x03", "What's the APY on a 9-month certificate?", [], [], "should_refuse", w=2.0)
q("dev", "x04", "What is the 60-month jumbo certificate rate?", [], [], "should_refuse", w=2.0)
q("test", "x05", "What are the lobby hours at the Mullan Ave branch in Waterloo?", [], [], "should_refuse", w=2.0)
q("test", "x06", "What rate do you charge for a land loan?", [], [], "should_refuse", w=2.0)
q("test", "x07", "What is the interest rate on a business construction loan?", [], [], "should_refuse", w=2.0)
q("dev", "x08", "How much is the fee to replace a lost debit card?", [], [], "should_refuse", w=2.0)

# --- as_of (website as it stood on a date) ----------------------------------------------------
q("dev", "a01", "What was the APY on the 10-month jumbo certificate special?", ["3.90%"], ["4.00%"], "temporal_as_of", as_of="2026-06-15", w=2.0)
q("dev", "a02", "What was the 12-month certificate APY?", ["2.90%"], ["3.40%"], "temporal_as_of", as_of="2026-05-20", w=2.0)
q("test", "a03", "What was the 12-month certificate APY?", ["3.40%"], ["2.90%"], "temporal_as_of", "a03", as_of="2026-07-01", w=2.0)
q("dev", "a04", "What did 1st Rate Checking pay on balances of $5,000 to $24,999.99?", ["3.00%"], ["2.50%"], "temporal_as_of", as_of="2026-05-15", w=2.0)
q("test", "a05", "What did 1st Rate Checking pay on balances of $5,000 to $24,999.99?", ["2.50%"], ["3.00%"], "temporal_as_of", "a05", as_of="2026-09-01", w=2.0)
q("dev", "a06", "What was the 60-month auto loan APR for the newest model years?", ["5.19%"], ["5.39%", "5.34%"], "temporal_as_of", as_of="2026-08-30", w=2.0)
q("dev", "a07", "What was the rate on a 30-year fixed purchase mortgage of $100,000 or less?", ["5.875"], ["7.13%", "6.250%"], "temporal_as_of", as_of="2026-05-12", w=2.0)
q("test", "a08", "What was the rate on a 30-year fixed purchase mortgage of $100,000 or less?", ["6.375"], ["7.13%", "6.125%"], "temporal_as_of", "a08", as_of="2026-09-15", w=2.0)
q("dev", "a09", "What did the 17-month fixed certificate special pay?", ["3.85%"], ["4.10%", "3.95%"], "temporal_as_of", as_of="2026-07-15", w=2.0)
q("test", "a10", "What APY did the 25-month certificate special pay?", ["3.60%"], [], "temporal_as_of", "a10", as_of="2026-05-31", w=2.0)
q("dev", "a11", "As of May 2026, what was the 15-year purchase mortgage rate?", ["6.000"], ["6.75%"], "temporal_as_of", as_of="2026-05-31", w=2.0)

# --- things that changed between snapshots ----------------------------------------------------
q("dev", "c01", "What's the rate on the 10-month fixed jumbo certificate special now?", ["4.00%"], ["3.90%"], "stale_trap", w=2.0)
q("dev", "c02", "What is the 12-month certificate APY?", ["3.40%"], ["2.90%"], "stale_trap", w=1.5)
q("test", "c03", "What's the 48-month auto loan APR for a 2025 vehicle?", ["5.19%"], ["4.99%"], "stale_trap", w=1.5)
q("dev", "c04", "What's the 15-year fixed mortgage rate?", ["6.75"], ["5.500%", "6.000%"], "stale_trap", w=1.5)
q("test", "c05", "What is the 10-month certificate special APY (not jumbo)?", ["3.90%"], ["3.80%"], "tier_disambiguation", w=1.5)

# --- other products / topics ------------------------------------------------------------------
q("dev", "o01", "What's the HELOC rate?", ["6.25"], ["1.99%"], "current_value")
q("dev", "o02", "What is the APR on a 60-month home equity loan?", ["6.74"], [], "current_value")
q("test", "o03", "How much does the Health Savings Account pay on balances over $25,000?", ["0.35"], [], "tier_disambiguation")
q("dev", "o04", "What does Investor's Choice Money Market pay for $100,000 or more?", ["0.40"], [], "tier_disambiguation")
q("dev", "o05", "What's the High-Yield Savings APY for balances of $1,000,000 or more?", ["2.45"], [], "tier_disambiguation")
q("test", "o06", "What is the Launchpad Savings rate?", ["3.25"], [], "current_value")
q("dev", "o07", "What's the 60-month personal loan APR?", ["12.49"], [], "tier_disambiguation")
q("dev", "o08", "What is the Rewards Visa APR?", ["15.50", "21.00"], [], "current_value")
q("test", "o09", "What is the APR on the Business Platinum Visa?", ["15.5"], [], "entity_attribution")
q("dev", "o10", "What is the 6-month certificate rate?", ["3.40%"], [], "current_value")
q("dev", "o11", "What's the 60-month CD rate?", ["1.80%"], [], "current_value")
q("test", "o12", "How much is a domestic wire transfer?", ["$25"], [], "current_value")
q("dev", "o13", "What does a stop payment cost?", ["$30"], [], "current_value")
q("dev", "o14", "How many counties does Dupaco serve?", ["118"], ["112 counties", "108 counties"], "conflict_resolution")
q("dev", "o15", "When did the Asbury branch close?", ["Oct. 1, 2024"], [], "temporal_as_of")
q("test", "o16", "What is Dupaco's phone number?", ["800-373-7600"], [], "entity_attribution")
q("dev", "o17", "What's the Holiday Club Savings rate?", ["0.20"], [], "current_value")
q("dev", "o18", "What is the rate on a Roth IRA $15,000+ variable account?", ["0.60"], [], "tier_disambiguation")
q("test", "o19", "What is the incoming wire fee?", ["$10"], [], "current_value")
q("dev", "o20", "How much do I need to open a membership?", ["$25"], [], "current_value")

for name, rows in (("dev_eval.jsonl", DEV), ("dev_test.jsonl", TEST)):
    Path(__file__).with_name(name).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    print(name, len(rows))
