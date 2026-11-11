"""编排器 LiveBrain（DESIGN §6.1）：三轨路由 + 判罚升级 + 打断调度 + 承诺核销。

事件处理顺序（每 tick）：
  平台事件入总线 -> 聚合窗口放行 -> 话术调度（打断判定）-> 处理一条事件
  -> 承诺核销 -> 收集完成的播报任务。

出稿统一后处理管线（_submit_speech）：
  三道过滤（品类宣称引擎）-> 话术原子展开+承诺扫描 -> 人设装饰 -> 等待播报。
"""
import asyncio
from typing import Any, Callable, Dict, List, Optional

from .bus import PriorityEventQueue
from .config import Settings
from .data import product_store, session as session_mod
from .data.audit import AuditLog
from .data.product_store import ProductStore
from .data.session import SessionState
from .decision import atoms, filters
from .decision.atoms import PromiseQueue, UnboundPromiseError
from .decision.fallback import FallbackSpeaker
from .decision.field_controller import FieldController
from .decision.knowledge_store import KnowledgeStore, seed_default as seed_knowledge
from .decision.llm_agent import MidTrackAgent, MockLLM
from .decision.persona import PersonaManager
from .decision.rule_engine import RuleEngine
from .decision.types import (PRIORITY_FILLER, PRIORITY_INTERACT,
                             PRIORITY_MID, PRIORITY_TEMPLATE, SpeechTask,
                             TRACK_MID, TRACK_FALLBACK)
from .events import (CONTROL, DANMU, JUDGMENT, METRIC, LiveEvent,
                     control_event)
from .execution.compliance import ComplianceNotArmed, ComplianceOverlay
from .execution.degradation import CapabilityChain
from .execution.pipeline import SpeechResult, StreamingPipeline
from .execution.renderer import MockRenderer
from .execution.tts import MockTTS
from .mixed.schedule import MixedSchedule
from .ops.takeover import TakeoverController
from .perception import classifier
from .perception.aggregator import (AggregatedQuestion, QuestionAggregator,
                                    ReplyBudget)
from .perception.classifier import (ACTION_REQUEST, INTERACT, NOISE,
                                    PRICE_STOCK, PRODUCT_CONSULT, SENSITIVE)
from .perception.sanitizer import sanitize
from .platform.mock_platform import MockPlatform
from .util import Clock, uid

_T_SENSITIVE = "这个我不能乱说哈，具体功效宝宝看商品详情页，或者问下客服更稳妥～"
_T_ACTION = "售后都有正规保障，具体政策宝宝看详情页的售后说明哈，我不敢随便打包票～"
_T_ESCALATED = "宝宝们，这个问题我看一下，信息以订单页和客服为准哈～"
_T_INTERACT = [
    "欢迎新来的宝宝，点个关注不迷路～",
    "我是 AI 虚拟主播哈，帮大家讲解产品，信息以详情页为准～",
    "谢谢宝宝的支持，爱你们～",
]
_T_FILLER = [
    "这个问题很好，我详细给她说下哈～",
    "宝宝稍等，我看一下哈，马上说～",
]


class LiveBrain:
    def __init__(self, platform: Optional[MockPlatform] = None,
                 settings: Optional[Settings] = None,
                 audit_path: Optional[str] = None,
                 speech_sink: Optional[Callable[[str, str], None]] = None,
                 llm_script: Optional[Dict[str, str]] = None,
                 llm_latency_s: float = 0.0,
                 room_id: str = "room-001",
                 avatar_store=None) -> None:
        self.settings = settings or Settings()
        self.clock = Clock(self.settings.clock_scale)
        self.audit = AuditLog(audit_path)
        self.room_id = room_id
        self.platform = platform or MockPlatform(room_id)
        self.avatar_store = avatar_store            # 形象资产（开播门禁，V4.2）

        # 数据层
        self.store = ProductStore()
        product_store.seed_default(self.store, self.clock.now())
        self.knowledge = KnowledgeStore()
        seed_knowledge(self.knowledge)
        self.session = SessionState(room_id, current_sku="SKU001",
                                    started_ts=self.clock.now())

        # 执行层
        self.compliance = ComplianceOverlay()
        self.pipeline = StreamingPipeline(
            tts=MockTTS("mock_tts"), renderer=MockRenderer("mock_renderer"),
            compliance=self.compliance, clock=self.clock, audit=self.audit,
            room_id=room_id, platform=self.platform, speech_sink=speech_sink)

        # 决策层
        self.persona = PersonaManager(self.settings)
        self.field = FieldController(self.settings)
        self.aggregator = QuestionAggregator(self.settings, self.clock)
        self.budget = ReplyBudget(self.settings.fast_reply_per_min,
                                  self.settings.llm_reply_per_min)
        self.promises = PromiseQueue(self.clock, self.audit, room_id=room_id)
        self.fallback = FallbackSpeaker()
        llm_primary = MockLLM("mock_llm_primary", script=llm_script or {},
                              latency_s=llm_latency_s)
        backup_script = {marker: response for marker, response
                         in (llm_script or {}).items() if response != "$FAIL"}
        llm_backup = MockLLM("mock_llm_backup", script=backup_script)
        self.llm_chain = CapabilityChain(
            "llm", [llm_primary, llm_backup], self.settings, self.audit,
            self.clock, room_id)
        self.mid_agent = MidTrackAgent(
            self.settings, self.clock, self.knowledge, self.llm_chain,
            self.fallback, self.audit, room_id)
        self.rule_engine = RuleEngine(self.store, self.settings, self.clock)
        self.takeover = TakeoverController(self.clock, self.audit, room_id)

        # 总线与调度
        self.bus = PriorityEventQueue()
        self.mixed = MixedSchedule(self.settings.mixed_schedule)   # 混播排班（V4.2）
        self.escalation = {"active": False, "reason": ""}
        self.alerts: List[str] = []
        self.judgments: List[LiveEvent] = []
        self.speech_results: List[SpeechResult] = []
        self._speak_task: Optional[asyncio.Future] = None
        self._pending_speech: List[SpeechTask] = []   # 待播队列（按优先级取）
        self._interact_counter = 0
        self._interact_index = 0
        self._filler_index = 0
        self.danmu_feed: List[Dict] = []     # 运营控制台弹幕流（含意图/隔离标记）
        self._started = False

    # ------------------------------------------------------------------
    # 生命周期与输入
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if not self.platform.registered:
            raise RuntimeError("平台未完成开播报备，拒绝开播（合规门禁）")
        if (self.avatar_store is not None
                and getattr(self.platform, "avatar_asset_id", None)):
            ok, reason = self.avatar_store.usable_on(
                self.platform.avatar_asset_id,
                self.platform.compliance_profile.platform,
                requires_registration=self.platform.compliance_profile.requires_registration)
            if not ok:
                raise RuntimeError("形象资产未通过开播门禁：%s" % reason)
        self.platform.start(self.clock.now())
        self.compliance.arm(self.platform.compliance_profile)
        self.mixed.begin(self.clock.now())
        self.audit.append("stream_start", self.room_id, {
            "profile": self.platform.compliance_profile.platform,
            "label": self.platform.compliance_profile.label_text,
            "area_ratio": self.platform.compliance_profile.min_area_ratio})
        self._started = True

    def schedule(self, delay_s: float, event: LiveEvent) -> None:
        self.platform.schedule(delay_s, event)

    async def run_until_idle(self, max_ticks: int = 4000) -> None:
        """处理到无事件、无待播话术、无待核销承诺为止（确定性驱动）。"""
        if not self._started:
            await self.start()
        for _ in range(max_ticks):
            alive = await self._tick()
            if not alive:
                return

    # ------------------------------------------------------------------
    # 调度循环
    # ------------------------------------------------------------------
    async def _tick(self) -> bool:
        progressed = False

        # 混播排班：边界跨越 -> 统一模式切换（V4.2）
        for transition in self.mixed.poll(self.clock.now()):
            await self._apply_mode_transition(transition)
            progressed = True

        for event in self.platform.poll(self.clock.now()):
            self.bus.publish(event)
            progressed = True

        for question in self.aggregator.flush_due():
            await self._route_question(question)
            progressed = True

        progressed |= await self._schedule_speech()

        if self.pipeline.in_human_mode and await self.pipeline.human_tick():
            progressed = True

        event = self.bus.get()
        if event is not None:
            await self._handle(event)
            progressed = True
        if self.promises.pending():
            await self.promises.execute_pending(self.platform)
            progressed = True

        self._collect_speak_result()
        if not progressed and (self.aggregator.pending()
                               or self.mixed.pending(self.clock.now())):
            await asyncio.sleep(0.002)   # 只剩聚合窗口/排班边界在等：避免空转
        else:
            await asyncio.sleep(0)       # 让播报任务推进一个控制点

        return bool(progressed or self.bus or self._speak_task
                    or self._pending_speech or self.platform.has_pending()
                    or self.promises.pending() or self.aggregator.pending()
                    or self.mixed.pending(self.clock.now())
                    or self.pipeline.in_human_mode)

    # ------------------------------------------------------------------
    # 混播模式切换（V4.2，DESIGN §7.7）：手动接管与排班切换共用入口
    # ------------------------------------------------------------------
    async def _apply_mode_transition(self, transition: Dict) -> None:
        if transition["to"] == "human":
            await self._enter_human("schedule:%s" % transition.get("label", ""))
        else:
            await self._exit_human(force=False, reason="schedule")

    async def _enter_human(self, reason: str) -> None:
        """切入真人：AI 静默 + 在播话术淡出 + 待播清空 + 画面切换。"""
        if self.takeover.ai_muted():
            return
        self.takeover.takeover(self.pipeline, reason)
        self.alerts.append("HUMAN_TAKEOVER:%s" % reason)
        if self._speak_task is not None:
            await asyncio.wait([self._speak_task])
            self._collect_speak_result()
        if self._pending_speech:
            self.audit.append("pending_dropped", self.room_id,
                              {"count": len(self._pending_speech),
                               "reason": reason})
            self._pending_speech = []
        capture = getattr(self.platform, "human_capture", None)
        await self.pipeline.begin_human_mode(capture)

    async def _exit_human(self, force: bool = False, reason: str = "manual") -> bool:
        """切回 AI：先过交回门（未核销承诺清点），再切回数字人画面。"""
        ok, info = self.takeover.rehandoff(
            self.promises, self.persona, self.session, force=force)
        if not ok:
            self.alerts.append("REHANDOFF_BLOCKED:%s" % info.get("reason", ""))
            return False
        await self.pipeline.end_human_mode()
        return True
    async def _schedule_speech(self) -> bool:
        progressed = False
        if self._speak_task is not None and self._speak_task.done():
            self._collect_speak_result()
            progressed = True
        if not self._pending_speech:
            return progressed
        if self.takeover.ai_muted():
            return progressed            # 真人段不启新 AI 话术（待播已清空，防御）

        if self._speak_task is None:
            task = self._pop_pending()
            self._speak_task = asyncio.ensure_future(self.pipeline.speak(task))
            return True

        current = self.pipeline.current_task
        top = min(self._pending_speech, key=lambda t: t.priority)
        if current is not None and top.priority < current.priority:
            # 打断：高优先级话术抢占（音频淡出 + 视觉过渡后接入）
            self.pipeline.request_interrupt()
            await asyncio.wait([self._speak_task])
            self._collect_speak_result()
            task = self._pop_pending()
            self._speak_task = asyncio.ensure_future(self.pipeline.speak(task))
            return True
        return progressed

    def _pop_pending(self) -> SpeechTask:
        """取最高优先级（数值最小）任务；同优先级先到先播。"""
        best = min(range(len(self._pending_speech)),
                   key=lambda i: (self._pending_speech[i].priority, i))
        return self._pending_speech.pop(best)

    def _collect_speak_result(self) -> None:
        if self._speak_task is None or not self._speak_task.done():
            return
        try:
            result = self._speak_task.result()
        except ComplianceNotArmed:
            self.alerts.append("COMPLIANCE_GATE_BLOCKED")
            self.audit.append("gate_blocked", self.room_id, {})
            self._speak_task = None
            return
        except Exception as exc:   # 管线异常：降级告警，直播不中断
            self.alerts.append("PIPELINE_ERROR:%s" % exc)
            self.audit.append("pipeline_error", self.room_id, {"error": str(exc)})
            self._speak_task = None
            return
        self._speak_task = None
        self.speech_results.append(result)
        self.session.note_utterance()
        for ops_action in result.task.ops:
            self.promises.submit(ops_action, result.utterance_id)
        for judgment in result.judgment_events:
            self.bus.publish(judgment)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------
    async def _handle(self, event: LiveEvent) -> None:
        if event.kind == JUDGMENT:
            self._handle_judgment(event)
        elif event.kind == CONTROL:
            await self._handle_control(event)
        elif event.kind == METRIC:
            self._handle_metric(event)
        elif event.kind == DANMU:
            await self._handle_danmu(event)

    def _handle_judgment(self, event: LiveEvent) -> None:
        self.judgments.append(event)
        self.escalation = {"active": True,
                           "reason": event.payload.get("reason", "")}
        self.alerts.append("JUDGMENT:%s:%s" % (event.payload.get("level"),
                                               event.payload.get("reason")))
        self.audit.append("judgment", self.room_id, dict(event.payload))

    async def _handle_control(self, event: LiveEvent) -> None:
        action = event.payload.get("action", "")
        params = event.payload.get("params", {})
        if action == "takeover":
            await self._enter_human(params.get("reason", "manual"))
        elif action == "rehandoff":
            await self._exit_human(force=params.get("force", False))
        elif action == "resume":
            self.escalation = {"active": False, "reason": ""}
            self.audit.append("escalation_resume", self.room_id,
                              {"by": params.get("by", "operator")})
        elif action == "persona_switch":
            ok, reason = self.persona.switch(
                params.get("persona_id", ""), source="manual")
            self.audit.append("persona_switch", self.room_id, {
                "persona_id": params.get("persona_id"), "ok": ok,
                "reason": reason})
        elif action == "switch_product":
            self.session.current_sku = params.get("sku", self.session.current_sku)
            self.audit.append("switch_product", self.room_id,
                              {"sku": self.session.current_sku})
        elif action == "human_ops":
            ops_action = atoms.OpsAction(params.get("op", ""),
                                         params.get("params", {}))
            result = await self.platform.ops(ops_action)
            self.takeover.human_ops(ops_action, result.detail)

    def _handle_metric(self, event: LiveEvent) -> None:
        online = int(event.payload.get("online", 0))
        stock_ratio = float(event.payload.get("stock_ratio", 1.0))
        self.session.online = online
        change = self.field.update(online, stock_ratio)
        if change:
            old, new, reason = change
            self.session.stage = new
            self.audit.append("stage_change", self.room_id, {
                "from": old, "to": new, "reason": reason})

    async def _handle_danmu(self, event: LiveEvent) -> None:
        user_id = event.payload.get("user_id", "u?")
        text = event.payload.get("text", "")
        now = self.clock.now()

        result = sanitize(text, self.settings.danmu_max_len)
        intent = None if result.quarantined else \
            classifier.classify(result.cleaned)
        self._note_danmu(user_id, text, intent,
                         quarantined=result.quarantined)
        if result.quarantined:
            self.audit.append("quarantine", self.room_id, {
                "user_id": user_id, "text": text[:60],
                "reasons": result.reasons})
            return
        if intent.intent == NOISE:
            return
        if self.takeover.ai_muted():
            return   # 真人接管期 AI 静默

        self.session.note_question(result.cleaned)

        if intent.intent == SENSITIVE:
            self._submit_template(_T_SENSITIVE, "template_sensitive",
                                  result.cleaned)
            return
        if intent.intent == ACTION_REQUEST:
            self._submit_template(_T_ACTION, "template_action",
                                  result.cleaned)
            return
        if intent.intent == PRICE_STOCK:
            if not intent.purchase_intent:
                if not self.budget.allow("fast", now):
                    self.audit.append("budget_drop", self.room_id, {
                        "track": "fast", "text": result.cleaned[:60]})
                    return
                self.budget.consume("fast", now)
            question = self.aggregator.add(
                intent.intent, intent.subtype, intent.topic_key,
                result.cleaned, user_id, intent.purchase_intent)
            if question:
                await self._route_question(question)
            return
        if intent.intent == PRODUCT_CONSULT:
            if self.escalation["active"]:
                self._submit_template(_T_ESCALATED, "template_escalated",
                                      result.cleaned)
                return
            if not intent.purchase_intent:
                if not self.budget.allow("llm", now):
                    self.audit.append("budget_drop", self.room_id, {
                        "track": "llm", "text": result.cleaned[:60]})
                    return
                self.budget.consume("llm", now)
            question = self.aggregator.add(
                intent.intent, intent.subtype, intent.topic_key,
                result.cleaned, user_id, intent.purchase_intent)
            if question:
                await self._route_question(question)
            return
        if intent.intent == INTERACT:
            self._maybe_reply_interact(result.cleaned)

    def _maybe_reply_interact(self, text: str) -> None:
        ratio = self.field.strategy().interact_reply_ratio
        self._interact_counter += 1
        step = max(1, int(round(1.0 / ratio))) if ratio < 1.0 else 1
        if self._interact_counter % step != 0:
            return
        template = _T_INTERACT[self._interact_index % len(_T_INTERACT)]
        self._interact_index += 1
        self._submit_template(template, "template_interact", text,
                              priority=PRIORITY_INTERACT)

    # ------------------------------------------------------------------
    # 路由与出稿
    # ------------------------------------------------------------------
    async def _route_question(self, question: AggregatedQuestion) -> None:
        # 聚合窗口放行的问题同样要过接管/判罚门（防止绕过降权与静默）
        if self.takeover.ai_muted():
            return
        if self.escalation["active"]:
            self._submit_template(_T_ESCALATED, "template_escalated",
                                  question.representative_text)
            return
        strategy = self.field.strategy()
        sku = self.session.current_sku

        if question.intent == PRICE_STOCK:
            task = self.rule_engine.answer(question, sku, strategy)
            if strategy.price_priority_boost:
                task.priority = max(
                    1, task.priority - strategy.price_priority_boost)
            submitted = self._submit_speech(task)
            if submitted is None:
                self.alerts.append("FAST_TRACK_BLOCKED")
            return

        if question.intent == PRODUCT_CONSULT:
            product = self.store.get(sku)
            if product is None:
                task = self.fallback.next(
                    "本品", self.session.online, strategy,
                    origin=question.representative_text, clock=self.clock)
                self._submit_speech(task)
                return
            if self.settings.emit_filler and not self.pipeline.busy:
                self._submit_filler(question.representative_text)
            task = await self.mid_agent.generate(
                question, product, self.persona, strategy,
                online=self.session.online)
            submitted = self._submit_speech(task)
            if submitted is None and task.track == TRACK_MID:
                # 中轨被承诺词拦截 -> 落兜底，绝不带病出稿
                fallback_task = self.fallback.next(
                    product.name, self.session.online, strategy,
                    origin=question.representative_text, clock=self.clock)
                self._submit_speech(fallback_task)

    def _submit_template(self, template: str, source: str, origin: str,
                         priority: int = PRIORITY_TEMPLATE) -> None:
        task = SpeechTask(
            task_id=uid("spk"), track="template", sentences=[template],
            priority=priority, emotion=self.field.strategy().emotion,
            ops=[], origin=origin, source=source, facts={},
            created_ts=self.clock.now())
        if self._submit_speech(task) is None:
            self.alerts.append("TEMPLATE_BLOCKED:%s" % source)

    def _submit_filler(self, origin: str) -> None:
        """等待期衔接话术：数字无关、承诺无关，最低优先级。

        管线空闲时直接开播（不等下一 tick——生成期间 tick 循环被
        await 阻塞，排队的话术永远轮不到）；正播报中则跳过。
        """
        if self._speak_task is not None:
            return
        template = _T_FILLER[self._filler_index % len(_T_FILLER)]
        self._filler_index += 1
        task = SpeechTask(
            task_id=uid("spk"), track="template", sentences=[template],
            priority=PRIORITY_FILLER, emotion=self.field.strategy().emotion,
            ops=[], origin=origin, source="template_filler", facts={},
            created_ts=self.clock.now())
        if self._submit_speech(task) is not None and self._speak_task is None:
            self._speak_task = asyncio.ensure_future(self.pipeline.speak(task))

    def _submit_speech(self, task: SpeechTask) -> Optional[SpeechTask]:
        """出稿统一后处理：过滤 -> 原子展开+承诺扫描 -> 人设装饰 -> 排队播报。"""
        # 正式话术到达即取代排队中的 filler（filler 只为填补等待期）
        if task.source != "template_filler":
            self._pending_speech = [
                t for t in self._pending_speech
                if t.source != "template_filler"]
        product = self.store.get(self.session.current_sku)
        category = product.category if product else ""
        qual_flags = product.qual_flags if product else []

        joined = "".join(task.sentences)
        verdict = filters.check(joined, category, qual_flags)
        if not verdict.passed:
            self.audit.append("filter_block", self.room_id, {
                "blocked": verdict.blocked, "track": task.track,
                "text": joined})
            return None

        final_sentences: List[str] = []
        ops_actions: List[atoms.OpsAction] = []
        try:
            for sentence in task.sentences:
                expanded, ops = atoms.expand(sentence)
                final_sentences.append(expanded)
                ops_actions.extend(ops)
        except UnboundPromiseError as exc:
            self.audit.append("promise_block", self.room_id, {
                "words": exc.words, "track": task.track, "text": joined})
            return None

        task.sentences = [self.persona.decorate(s) for s in final_sentences]
        task.ops = ops_actions

        self._pending_speech.append(task)
        return task

    def _note_danmu(self, user_id: str, text: str,
                    intent: Optional[classifier.IntentResult],
                    quarantined: bool) -> None:
        """运营控制台弹幕流（最近 60 条，含意图与隔离标记）。"""
        self.danmu_feed.append({
            "ts": self.clock.now(),
            "user": user_id,
            "text": text[:60],
            "intent": intent.intent if intent else "injection",
            "subtype": intent.subtype if intent else "",
            "quarantined": quarantined,
        })
        if len(self.danmu_feed) > 60:
            self.danmu_feed = self.danmu_feed[-60:]

    # ------------------------------------------------------------------
    # 观测
    # ------------------------------------------------------------------
    def state_snapshot(self) -> Dict:
        """运营控制台/外部监控用状态快照（在编排器事件循环内调用）。"""
        pipeline = self.pipeline
        if pipeline.in_human_mode:
            visual = "human" if getattr(self.platform, "human_capture", None) \
                else "avatar_idle"
        else:
            visual = "avatar"
        switches = [e for e in pipeline.log if e["type"] == "switch_source"]
        recent_speech = [{
            "ts": 0.0,
            "track": r.task.track,
            "source": r.task.source,
            "text": r.spoken_text[:80],
            "origin": r.task.origin[:40],
            "interrupted": r.interrupted,
            "emotion": r.task.emotion,
        } for r in self.speech_results[-15:]]
        return {
            "room": self.room_id,
            "started": self._started,
            "stage": self.field.stage,
            "stage_strategy": {
                "interact_ratio": self.field.strategy().interact_reply_ratio,
                "emotion": self.field.strategy().emotion,
            },
            "persona": self.persona.current.persona_id,
            "persona_name": self.persona.current.name,
            "mode": "human" if self.takeover.ai_muted() else "ai",
            "escalation": dict(self.escalation),
            "online": self.session.online,
            "current_sku": self.session.current_sku,
            "visual_source": visual,
            "visual_history": [e["to"] for e in switches[-4:]],
            "compliance": {
                "armed": self.compliance.armed,
                "label": self.compliance.profile.label_text
                         if self.compliance.profile else "",
                "policy": getattr(self.compliance.profile, "label_policy", "")
                          if self.compliance.profile else "",
            },
            "speech": list(reversed(recent_speech)),      # 新的在前
            "danmu_feed": list(reversed(self.danmu_feed[-25:])),
            "promises": [{
                "id": p.promise_id, "action": p.ops.action,
                "status": p.status, "failures": p.failures,
            } for p in self.promises.promises[-10:]],
            "judgments": [{"reason": j.payload.get("reason"),
                           "level": j.payload.get("level")}
                          for j in self.judgments[-5:]],
            "alerts": self.alerts[-10:],
            "providers": {
                "llm": self.llm_chain.current_name(),
                "llm_switches": len(self.llm_chain.switch_log),
            },
            "mixed": {
                "segments": [{"duration_s": s.duration_s, "mode": s.mode,
                              "label": s.label}
                             for s in self.mixed.segments],
                "current_mode": self.mixed.current_mode(),
                "pos": self.mixed._pos,
            },
            "audit": {
                "count": len(self.audit.entries),
                "verified": self.audit.verify()[0],
                "quarantined": self.audit.count("quarantine"),
                "promise_blocks": self.audit.count("promise_block"),
                "generation_rejected": self.audit.count("generation_rejected"),
            },
            "stats": {
                "utterances": len(self.speech_results),
                "interrupted": sum(1 for r in self.speech_results
                                   if r.interrupted),
            },
        }
    def spoken_texts(self) -> List[str]:
        return [r.spoken_text for r in self.speech_results]

    def llm_seen_user_inputs(self) -> List[str]:
        texts: List[str] = []
        for provider in self.llm_chain.providers:
            mock = provider
            texts.extend(m["content"] for m in getattr(mock, "seen_messages", []))
        return texts
