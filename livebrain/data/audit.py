"""审计总线（DESIGN §8.3/§8.4）：追加式 JSONL + SHA256 哈希链。

- 覆盖 AI 话术与人工操作（R10）；
- 帧级追溯 v2（R8）：每话术关联帧区间与检查点哈希，"可证明未篡改"
  由追加式存储 + 哈希链达成，不承诺跨硬件重渲染复现；
- verify() 供监管核查与日常巡检：篡改任意条目即可定位。
"""
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..util import canonical_json, sha256_hex

GENESIS = sha256_hex("livebrain-audit-genesis-v1")


@dataclass
class AuditEntry:
    seq: int
    ts: float
    type: str
    room_id: str
    payload: Dict[str, Any]
    prev_hash: str
    entry_hash: str


class AuditLog:
    def __init__(self, path: Optional[str] = None) -> None:
        self.entries: List[AuditEntry] = []
        self._last_hash = GENESIS
        self._fh = None
        if path:
            self._fh = open(path, "a", encoding="utf-8")

    def append(self, type_: str, room_id: str = "",
               payload: Optional[Dict[str, Any]] = None) -> AuditEntry:
        core = {
            "seq": len(self.entries) + 1,
            "ts": time.time(),
            "type": type_,
            "room_id": room_id,
            "payload": payload or {},
        }
        entry_hash = sha256_hex(self._last_hash + canonical_json(core))
        entry = AuditEntry(prev_hash=self._last_hash, entry_hash=entry_hash, **core)
        self.entries.append(entry)
        self._last_hash = entry_hash
        if self._fh:
            self._fh.write(canonical_json({
                "seq": entry.seq, "ts": entry.ts, "type": entry.type,
                "room_id": entry.room_id, "payload": entry.payload,
                "prev_hash": entry.prev_hash, "entry_hash": entry.entry_hash,
            }) + "\n")
            self._fh.flush()
        return entry

    def verify(self) -> Tuple[bool, Optional[int]]:
        """逐条重算哈希并核对链式 prev_hash。返回 (是否完好, 首个坏损 seq)。"""
        prev = GENESIS
        for entry in self.entries:
            core = {
                "seq": entry.seq, "ts": entry.ts, "type": entry.type,
                "room_id": entry.room_id, "payload": entry.payload,
            }
            expect = sha256_hex(prev + canonical_json(core))
            if entry.prev_hash != prev or entry.entry_hash != expect:
                return False, entry.seq
            prev = entry.entry_hash
        return True, None

    def by_type(self, type_: str) -> List[AuditEntry]:
        return [e for e in self.entries if e.type == type_]

    def count(self, type_: str) -> int:
        return len(self.by_type(type_))

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
