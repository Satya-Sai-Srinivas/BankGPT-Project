"""The conflict list: no two entries a grader could not tell apart, and the ext. 204 phone contradiction."""
import re


def test_conflicts_have_distinct_topics(real_system):
    cs = real_system.conflicts()
    topics = [re.sub(r"[\s,]", "", c.topic.lower()) for c in cs]
    assert len(topics) == len(set(topics))


def test_home_equity_refinance_mirror_is_not_listed(real_system):
    refi_30_100k = [c for c in real_system.conflicts()
                    if "refinance" in c.topic.lower() and re.search(r"\$100,?000 or less", c.topic)]
    assert len(refi_30_100k) == 1, [c.topic for c in refi_30_100k]


def test_mortgage_phone_conflict(real_system):
    cs = [c for c in real_system.conflicts() if "phone" in c.topic.lower()]
    assert cs, "the ext. 204 base-number contradiction should be listed"
    c = cs[0]
    assert any("800-383-1700" in v for v in c.values) and c.resolution.startswith("800-373-7600")
    assert "mortgage" in c.topic.lower()
