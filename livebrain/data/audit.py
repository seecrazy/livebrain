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
    def __init__(self, path: Optional[str] = None,
                 max_memory_entries: int = 50000) -> None:
        self.entries: List[AuditEntry] = []
        self._last_hash = GENESIS
        self._fh = None
        self._fh_pending = 0                    # 批量落盘（批1 性能）
        self._fh_last_flush = time.time()
        if path:
            self._fh = open(path, "a", encoding="utf-8")
        # 长直播保护（P0-2）：内存环形上限 + 裁剪锚点（全量日志仍在 JSONL 文件）
        self.max_memory_entries = max_memory_entries
        self._anchor_hash = GENESIS
        self._anchor_seq = 0
        self.dropped_entries = 0
        # 增量校验游标（控制台轮询用）：verified_fast() 只重算新增条目
        self._verify_cursor = 0
        self._verify_hash = GENESIS

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
        self._trim()
        if self._fh:
            self._fh.write(canonical_json({
                "seq": entry.seq, "ts": entry.ts, "type": entry.type,
                "room_id": entry.room_id, "payload": entry.payload,
                "prev_hash": entry.prev_hash, "entry_hash": entry.entry_hash,
            }) + "\n")
            self._fh_pending += 1
            # 批量 flush：每 20 条或满 1 秒落盘一次（崩溃最多丢 1 秒尾部）
            if (self._fh_pending >= 20
                    or time.time() - self._fh_last_flush >= 1.0):
                self._fh.flush()
                self._fh_pending = 0
                self._fh_last_flush = time.time()
        return entry

    def _trim(self) -> None:
        """超出内存上限时裁剪最旧条目：锚点链保证剩余部分仍可校验。"""
        if len(self.entries) <= self.max_memory_entries:
            return
        drop = len(self.entries) - self.max_memory_entries
        anchor = self.entries[drop - 1]
        self._anchor_hash = anchor.entry_hash
        self._anchor_seq = anchor.seq
        self.dropped_entries += drop
        self.entries = self.entries[drop:]
        self._verify_cursor = 0                    # 增量游标对齐新锚点
        self._verify_hash = self._anchor_hash

    def _core_of(self, entry: AuditEntry) -> Dict:
        return {
            "seq": entry.seq, "ts": entry.ts, "type": entry.type,
            "room_id": entry.room_id, "payload": entry.payload,
        }

    def verify(self) -> Tuple[bool, Optional[int]]:
        """逐条重算哈希并核对链式 prev_hash（监管核查/回放用，全量）。

        内存裁剪过的最旧条目以锚点为起点（完整链在 JSONL 文件）。
        """
        prev = self._anchor_hash
        for entry in self.entries:
            expect = sha256_hex(prev + canonical_json(self._core_of(entry)))
            if entry.prev_hash != prev or entry.entry_hash != expect:
                return False, entry.seq
            prev = entry.entry_hash
        return True, None

    def verified_fast(self) -> bool:
        """增量校验（控制台轮询用）：只重算上次校验之后的新增条目。

        O(新增) 而非 O(全量)，长直播下 CPU 恒定；发现坏点后每次都复核坏点。
        篡改历史条目的全量检测仍走 verify()。
        """
        if self._verify_cursor > len(self.entries):    # 裁剪导致游标回退
            self._verify_cursor = 0
            self._verify_hash = self._anchor_hash
        prev = self._verify_hash
        while self._verify_cursor < len(self.entries):
            entry = self.entries[self._verify_cursor]
            expect = sha256_hex(prev + canonical_json(self._core_of(entry)))
            if entry.prev_hash != prev or entry.entry_hash != expect:
                return False
            prev = entry.entry_hash
            self._verify_cursor += 1
        self._verify_hash = prev if self.entries else self._anchor_hash
        return True

    def by_type(self, type_: str) -> List[AuditEntry]:
        return [e for e in self.entries if e.type == type_]

    def count(self, type_: str) -> int:
        return len(self.by_type(type_))

    def close(self) -> None:
        if self._fh:
            self._fh.flush()
            self._fh.close()
            self._fh = None
