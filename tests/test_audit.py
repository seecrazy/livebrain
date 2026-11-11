"""审计总线哈希链（DESIGN §8.3/§8.4）：可证明未篡改。"""
import os
import tempfile

from livebrain.data.audit import AuditLog


def test_chain_verifies_when_intact():
    audit = AuditLog()
    for i in range(10):
        audit.append("utterance", "r1", {"i": i, "text": "话术%d" % i})
    ok, bad = audit.verify()
    assert ok and bad is None
    assert audit.count("utterance") == 10


def test_tampered_payload_detected():
    audit = AuditLog()
    for i in range(5):
        audit.append("utterance", "r1", {"i": i})
    audit.entries[2].payload["i"] = 999              # 事后篡改
    ok, bad = audit.verify()
    assert not ok and bad == 3                        # 定位到被改条目 seq


def test_tampered_hash_detected():
    audit = AuditLog()
    audit.append("utterance", "r1", {"i": 1})
    audit.append("judgment", "r1", {"level": "warn"})
    audit.entries[1].entry_hash = "0" * 64
    ok, bad = audit.verify()
    assert not ok and bad == 2


def test_prev_hash_linkage_enforced():
    audit = AuditLog()
    audit.append("quarantine", "r1", {"text": "x"})
    audit.append("quarantine", "r1", {"text": "y"})
    audit.entries[1].prev_hash = "f" * 64    # 伪造链条衔接
    ok, _bad = audit.verify()
    assert ok is False


def test_persistence_roundtrip():
    path = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
    audit = AuditLog(path)
    audit.append("utterance", "r1", {"text": "只要{price}"})
    audit.append("provider_switch", "r1", {"from": "a", "to": "b"})
    audit.close()
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().strip().split("\n")
    assert len(lines) == 2
    import json
    entry = json.loads(lines[0])
    assert entry["type"] == "utterance" and entry["prev_hash"]
