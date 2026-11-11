"""形象资产管理（V4.2 增补，DESIGN §8.6）：形象库 + 授权 + 报备绑定。

合规规则（接入层开播门禁）：
- 真人底模（real_person_model）：必须有肖像授权且在有效期内，否则拒绝开播；
- 数字人形象（digital_human）：平台要求形象报备时必须已绑定报备记录；
- 未通过 usable_on 校验 -> LiveBrain.start() 直接 RuntimeError（不可绕过）。
M1 内存实现；M2+ 平移 PG（表结构并入 deploy/schema.sql）。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DIGITAL_HUMAN = "digital_human"
REAL_PERSON_MODEL = "real_person_model"


@dataclass
class Authorization:
    doc_ref: str                   # 授权文件引用（合同编号/存证哈希）
    licensor: str                  # 授权人（肖像权人/经纪约主体）
    scope: str                     # 授权范围（平台/用途/期限说明）
    valid_until: float             # 有效期（epoch 秒）


@dataclass
class AvatarAsset:
    asset_id: str
    name: str
    kind: str                                  # digital_human / real_person_model
    image_ref: str = ""                        # 底模/形象照引用
    authorization: Optional[Authorization] = None
    registration_platforms: Dict[str, str] = field(default_factory=dict)
    linked_persona: str = ""                   # 绑定的人设 ID（可选）


class AvatarAssetStore:
    def __init__(self, clock=None) -> None:
        self._assets: Dict[str, AvatarAsset] = {}
        self._clock = clock

    def upsert(self, asset: AvatarAsset) -> None:
        self._assets[asset.asset_id] = asset

    def get(self, asset_id: str) -> Optional[AvatarAsset]:
        return self._assets.get(asset_id)

    def list(self) -> List[AvatarAsset]:
        return list(self._assets.values())

    def usable_on(self, asset_id: str, platform: str,
                  requires_registration: bool = True) -> Tuple[bool, str]:
        """开播门禁校验：形象授权 + 平台报备绑定。"""
        asset = self._assets.get(asset_id)
        if asset is None:
            return False, "asset_not_found"

        if asset.kind == REAL_PERSON_MODEL:
            auth = asset.authorization
            if auth is None:
                return False, "authorization_missing"
            now = self._clock.now() if self._clock else 0.0
            if now and auth.valid_until <= now:
                return False, "authorization_expired"

        if requires_registration:
            reg = asset.registration_platforms.get(platform)
            if not reg:
                return False, "registration_missing:%s" % platform

        return True, "ok"


def seed_default(store: AvatarAssetStore, clock=None) -> None:
    """默认演示形象：合规数字人 + 一个已授权真人底模。"""
    store.upsert(AvatarAsset(
        asset_id="ava-001", name="小甜（数字人）", kind=DIGITAL_HUMAN,
        image_ref="models/xiaotian_v2.safetensors",
        registration_platforms={"mock": "REG-MOCK-2026-001"},
        linked_persona="xiaotian"))
    valid_until = (clock.now() + 86400 * 365) if clock else 4102444800.0
    store.upsert(AvatarAsset(
        asset_id="ava-002", name="品牌主理人（真人底模）",
        kind=REAL_PERSON_MODEL, image_ref="talent/owner_contract.pdf",
        authorization=Authorization(
            doc_ref="AUTH-2026-118", licensor="品牌方主理人",
            scope="直播电商数字人形象，限本店直播间", valid_until=valid_until),
        registration_platforms={"mock": "REG-MOCK-2026-002"}))
