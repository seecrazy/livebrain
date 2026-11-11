"""形象资产管理（V4.2，DESIGN §8.6）：授权校验 + 报备绑定 + 开播门禁。"""
import asyncio

from livebrain.data.avatar_store import (AvatarAsset, AvatarAssetStore,
                                         Authorization, DIGITAL_HUMAN,
                                         REAL_PERSON_MODEL, seed_default)
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform
from tests.helpers import FakeClock


def _store():
    clock = FakeClock(start=1000000.0)
    return AvatarAssetStore(clock=clock), clock


def test_real_person_model_requires_authorization():
    store, _clock = _store()
    store.upsert(AvatarAsset("a1", "真人底模", REAL_PERSON_MODEL))
    ok, reason = store.usable_on("a1", "mock")
    assert not ok and reason == "authorization_missing"


def test_real_person_model_expired_authorization():
    store, clock = _store()
    store.upsert(AvatarAsset("a1", "真人底模", REAL_PERSON_MODEL,
                             authorization=Authorization(
                                 "doc-1", "授权人", "直播用途",
                                 valid_until=clock.now() - 1)))
    ok, reason = store.usable_on("a1", "mock")
    assert not ok and reason == "authorization_expired"


def test_real_person_model_valid_with_registration():
    store, clock = _store()
    store.upsert(AvatarAsset("a1", "真人底模", REAL_PERSON_MODEL,
                             authorization=Authorization(
                                 "doc-1", "授权人", "直播用途",
                                 valid_until=clock.now() + 86400),
                             registration_platforms={"mock": "REG-1"}))
    ok, reason = store.usable_on("a1", "mock")
    assert ok and reason == "ok"
    # 平台要求报备但未绑定该平台
    ok2, reason2 = store.usable_on("a1", "douyin")
    assert not ok2 and reason2.startswith("registration_missing")


def test_digital_human_registration_gate():
    store, _clock = _store()
    store.upsert(AvatarAsset("d1", "数字人", DIGITAL_HUMAN))   # 无授权也允许
    ok, reason = store.usable_on("d1", "mock", requires_registration=True)
    assert not ok and reason.startswith("registration_missing")
    store.upsert(AvatarAsset("d1", "数字人", DIGITAL_HUMAN,
                             registration_platforms={"mock": "REG-9"}))
    assert store.usable_on("d1", "mock")[0]
    # 平台不要求报备 -> 放行
    assert store.usable_on("d1", "other", requires_registration=False)[0]


def test_unknown_asset_rejected():
    store, _clock = _store()
    assert store.usable_on("nobody", "mock") == (False, "asset_not_found")


def test_seed_default_assets_usable():
    store, clock = _store()
    seed_default(store, clock)
    assert store.usable_on("ava-001", "mock")[0]
    assert store.usable_on("ava-002", "mock")[0]


def test_stream_start_gate_blocks_unauthorized_avatar():
    store, _clock = _store()
    store.upsert(AvatarAsset("bad", "未授权真人底模", REAL_PERSON_MODEL))
    platform = MockPlatform("room-gate", avatar_asset_id="bad")
    brain = LiveBrain(platform=platform, avatar_store=store, room_id="room-gate")
    try:
        asyncio.run(brain.start())
    except RuntimeError as exc:
        assert "authorization_missing" in str(exc)
    else:
        raise AssertionError("未授权形象必须拒绝开播")


def test_stream_start_gate_passes_authorized_avatar():
    store, clock = _store()
    seed_default(store, clock)
    platform = MockPlatform("room-ok", avatar_asset_id="ava-002")
    brain = LiveBrain(platform=platform, avatar_store=store, room_id="room-ok")
    asyncio.run(brain.start())            # 不抛错即通过
    assert brain.compliance.armed
