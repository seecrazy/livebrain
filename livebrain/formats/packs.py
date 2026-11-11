"""内置五个场景包（V4.4）：电商 / 聊天 / 唱歌 / 单口相声·脱口秀 / 多人相声。

内容种子全部原创（段子/对词/话题），规避版权；唱歌场景只报幕不输出
歌词（演唱/伴奏音轨属 M3 接入项），曲库白名单即版权授权清单。
"""
from typing import List, Optional

from ..decision.field_controller import StageStrategy
from .base import RoomFormat, build_task, register
from .creative import CreativeWriter, ai_task

# ---------------------------------------------------------------- 电商带货
class EcommerceFormat(RoomFormat):
    format_id = "ecommerce"
    display_name = "电商带货"

    def view(self, brain):
        product = brain.store.get(brain.session.current_sku)
        return {"当前讲品": product.name if product else "—",
                "库存比": "%.0f%%" % (product.stock_ratio() * 100)
                          if product else "—"}

    async def proactive(self, brain) -> Optional[object]:
        """空闲排品推进：复用兜底话术池（防机械重复设计同样适用）。"""
        product = brain.store.get(brain.session.current_sku)
        name = product.name if product else "本品"
        return brain.fallback.next(
            name, brain.session.online, brain.field.strategy(),
            origin="排品推进", clock=brain.clock)


# ---------------------------------------------------------------- 聊天陪伴
class ChatFormat(RoomFormat):
    format_id = "chat"
    display_name = "聊天陪伴"
    default_persona = "nuannuan"
    sensitive_template = "这个我不太懂哈，专业的事得问专业的人，咱们聊点开心的～"
    action_template = "咱们直播间不打包票哈，好好陪伴最重要～"
    stage_display = {"warmup": "开场热聊", "explain": "话题进行中",
                     "closing": "深度陪伴", "valley": "冷场救场"}

    TOPICS: List[str] = [
        "今天过得怎么样？评论区聊聊，好的坏的我都在听～",
        "问大家一个老问题：如果周末完全属于自己，你最想干什么？",
        "分享一个最近让我开心的小事：楼下猫今天肯让我摸头了～",
        "有没有一首歌，你一听就想起某个人？打在评论区～",
        "深夜话题：你最想对五年前的自己说哪句话？",
        "聊聊最近追的剧呗，我记下来陪你们一起追～",
        "今天学到一个冷知识：企鹅的膝盖藏在羽毛里，惊不惊喜？",
        "评论区接龙：用一个词形容今天的心情，我先来——稳稳的～",
    ]

    def stage_strategies(self):
        return {
            "warmup": StageStrategy("warmup", 1.0, 0, "warm"),
            "explain": StageStrategy("explain", 0.6, 0, "cozy"),
            "closing": StageStrategy("closing", 0.8, 0, "warm"),
            "valley": StageStrategy("valley", 1.0, 0, "playful"),
        }

    def __init__(self):
        self._topic_pos = 0
        self.topics = list(self.TOPICS)     # 可被 --data 装载覆盖
        self._user_content = False          # --data 提供过内容则优先用户

    async def proactive(self, brain):
        if (brain.settings.creative_llm and not self._user_content):
            lines = await CreativeWriter(brain).generate(
                "topic", "人设：%s。当前阶段：%s。刚聊过：%s" % (
                    brain.persona.current.name, brain.field.stage,
                    brain.speech_results[-1].spoken_text[:30]
                    if brain.speech_results else "开播暖场"),
                sentences=1)
            if lines:
                return ai_task(brain, lines, source="format:topic_ai",
                               origin="AI话题", emotion="warm")
        topic = self.topics[self._topic_pos % len(self.topics)]
        self._topic_pos += 1
        return build_task([topic], source="format:topic",
                          origin="话题推进", clock=brain.clock)

    INTERACT = ["来啦？坐，正好聊到有意思的地方～", "哈哈哈被你发现了～",
                "评论区聊起来，我都看着呢～"]

    def view(self, brain):
        # 话题循环使用，进度按本轮位置显示（避免无限累加出现 6/4）
        return {"话题进度": "%d/%d" % (self._topic_pos % len(self.topics) + 1,
                                      len(self.topics)),
                "内容来源": "用户话题库" if self._user_content else "AI 原创+内置"}

    def interact_reply(self, brain):
        return self.INTERACT[self._topic_pos % len(self.INTERACT)]

    def gift_thanks(self, brain, user_id, gift, count):
        return build_task(
            ["谢谢{name}的{gift}，被你惦记着真好，今晚多陪你们一会儿～".format(
                name=user_id, gift=gift)],
            source="format:gift_thanks", origin="gift:%s" % gift,
            clock=brain.clock)


# ---------------------------------------------------------------- 唱歌演艺
class MusicFormat(RoomFormat):
    format_id = "music"
    display_name = "唱歌演艺"
    sensitive_template = "这个咱不接话哈，好好听歌～"
    action_template = "承诺就不下了，歌单管够～"
    stage_display = {"warmup": "开嗓暖场", "explain": "点歌演唱中",
                     "closing": "安可环节", "valley": "互动拉气氛"}

    # 版权白名单 = 已获授权曲库（演示数据；实际接入版权方清单）
    WHITELIST: List[str] = ["月亮代表我的心", "甜蜜蜜", "朋友", "童话"]

    DECLINE = "这首的授权咱们曲库里还没有哈，宝宝从点歌单里挑一个，都给你安排～"
    ANNOUNCE = "下一首《{song}》，送给点歌的宝宝，也送给在座的每一位～"

    INTERACT = ["谢谢宝宝捧场，想听什么点起来～", "咱们曲库随时安排～",
                "这首歌送给评论区所有宝宝～"]

    def interact_reply(self, brain):
        return self.INTERACT[len(self.served) % len(self.INTERACT)]

    def stage_strategies(self):
        return {
            "warmup": StageStrategy("warmup", 1.0, 0, "cheerful"),
            "explain": StageStrategy("explain", 0.4, 0, "singing"),
            "closing": StageStrategy("closing", 0.6, 0, "cheerful"),
            "valley": StageStrategy("valley", 0.9, 0, "playful"),
        }

    def __init__(self):
        self.queue: List[str] = []
        self.served: List[str] = []
        self.whitelist = list(self.WHITELIST)   # 授权曲库，可被 --data 装载覆盖

    def _match(self, text: str) -> Optional[str]:
        for song in self.whitelist:
            if song in text:
                return song
        return None

    def view(self, brain):
        return {"点歌队列": "、".join(self.queue) or "（空）",
                "最近已唱": "、".join(self.served[-3:]) or "—",
                "授权曲库": "%d 首" % len(self.whitelist)}

    def handle_song_request(self, brain, text, user_id):
        song = self._match(text)
        if song is None:
            return build_task([self.DECLINE], source="format:song_decline",
                              origin=text, clock=brain.clock)
        self.queue.append(song)
        return build_task(
            ["收到！《%s》安排上了，前面还有 %d 首，点歌的宝宝稍等～"
             % (song, max(0, len(self.queue) - 1))],
            source="format:song_ack", origin=text, clock=brain.clock)

    async def proactive(self, brain):
        """节目推进：队首出歌报幕（演唱音轨 M3 接入，当前为报幕话术）。
        版权白名单不可 AI 生成：音乐授权是法律约束，必须用户/内置显式提供。"""
        if not self.queue:
            return build_task(
                ["点歌单随时更新，想听什么打在评论区，授权曲库里都安排～"],
                source="format:song_idle", origin="点歌引导", clock=brain.clock)
        song = self.queue.pop(0)
        self.served.append(song)
        return build_task([self.ANNOUNCE.format(song=song)],
                          source="format:song_announce",
                          origin="演唱:%s" % song, clock=brain.clock)


# ------------------------------------------------- 单口相声 / 脱口秀
class StandupFormat(RoomFormat):
    format_id = "standup"
    display_name = "单口相声·脱口秀"
    default_persona = "duoge"
    sensitive_template = "这种话头我可不敢接，包袱可以有，这个真没有～"
    action_template = "不打包票哈，笑果管饱～"
    stage_display = {"warmup": "开场热场", "explain": "段子进行中",
                     "closing": "压轴大段", "valley": "冷场救场"}

    JOKES: List[dict] = [
        {"id": "j1", "setup": "我们家猫最近学会开门了，特别自豪，天天开。",
         "punch": "我提醒它房租是我交的，它看了我一眼，把门关上了。"},
        {"id": "j2", "setup": "朋友劝我健身，说练完浑身舒畅。",
         "punch": "我练了一组深蹲，现在下楼用扶手，舒畅得直哼哼。"},
        {"id": "j3", "setup": "我买了个智能音箱，说句话就能控制全屋。",
         "punch": "昨晚我说灯关了睡吧，它给我播了首《好运来》，说祝我做个好梦。"},
        {"id": "j4", "setup": "同事说他记性特别好，过目不忘。",
         "punch": "我让他帮我带杯咖啡，他忘了；第二天他跟我解释，说他没忘，是咖啡自己没跟上。"},
    ]

    INTERACT = ["谢谢捧场！包袱管够～", "您可太懂了，这正是下一段的梗～",
                "笑声就是掌声，收到～"]

    def interact_reply(self, brain):
        return self.INTERACT[self._pos % len(self.INTERACT)]

    def stage_strategies(self):
        return {
            "warmup": StageStrategy("warmup", 1.0, 0, "playful"),
            "explain": StageStrategy("explain", 0.3, 0, "witty"),
            "closing": StageStrategy("closing", 0.5, 0, "witty"),
            "valley": StageStrategy("valley", 0.9, 0, "playful"),
        }

    def __init__(self):
        self._pos = 0
        self._current: Optional[dict] = None
        self.jokes = list(self.JOKES)      # 可被 --data 装载覆盖
        self._user_content = False
        self._resume_punch: Optional[dict] = None   # 被打断段子的续讲位

    def _next_joke(self) -> dict:
        joke = self.jokes[self._pos % len(self.jokes)]
        self._pos += 1
        return joke

    def _joke_task(self, joke: dict, brain):
        self._current = joke
        return build_task([joke["setup"], joke["punch"]],
                          source="format:joke", origin="段子:%s" % joke["id"],
                          emotion="witty", clock=brain.clock)

    async def proactive(self, brain):
        if self._resume_punch is not None:         # 从包袱续讲（P1-7）
            joke = self._resume_punch
            self._resume_punch = None
            self._current = joke
            return build_task([joke["punch"]], source="format:joke_resume",
                              origin="续包袱:%s" % joke["id"], emotion="witty",
                              clock=brain.clock)
        if (brain.settings.creative_llm and not self._user_content):
            lines = await CreativeWriter(brain).generate(
                "joke", "人设：%s。直播场景：脱口秀。原创一个新段子。" %
                brain.persona.current.name, sentences=2)
            if lines:
                return ai_task(brain, lines, source="format:joke_ai",
                               origin="AI段子")
        return self._joke_task(self._next_joke(), brain)

    def view(self, brain):
        # 段子循环使用，进度按本轮位置显示（避免无限累加出现 73/4）
        pos = (self._pos - 1) % len(self.jokes) + 1 if self._pos else 0
        return {"段子进度": "%d/%d" % (pos, len(self.jokes)),
                "内容来源": "用户段子库" if self._user_content else "AI 原创+内置",
                "待续包袱": self._resume_punch["id"] if self._resume_punch else "—"}

    def handle_joke_request(self, brain, text, user_id):
        return self._joke_task(self._next_joke(), brain)

    def on_speech_done(self, brain, result) -> None:
        """被打断的段子不算讲完：铺垫已讲 -> 从包袱续；没开口 -> 整段回炉。"""
        if result.task.source not in ("format:joke", "format:joke_resume"):
            return
        if result.interrupted and self._current:
            if result.sentences_spoken == 1:
                self._resume_punch = self._current      # 观众听过铺垫，从包袱续
            else:
                self._pos = (self._pos - 1) % len(self.jokes)
        self._current = None


# ------------------------------------------------- 多人相声（对词轮转）
class CrosstalkFormat(RoomFormat):
    """多人相声：双角色对词轮转（逗哏 A / 捧哏 B）。

    单渲染通道下的"声音轮换"演绎；双形象同台/画中画属 M3 双主播通道
    （DESIGN §10.1），届时同一脚本直接映射到双通道。
    """

    format_id = "crosstalk"
    display_name = "多人相声"
    default_persona = "duoge"
    sensitive_template = "这包袱太大了，我们接不动～"
    action_template = "口说无凭，乐呵管够～"
    stage_display = {"warmup": "垫话开场", "explain": "正活进行中",
                     "closing": "底活收尾", "valley": "现挂救场"}

    # 对词脚本：role A=逗哏(活泼) B=捧哏(沉稳)
    SCRIPT: List[dict] = [
        {"role": "A", "line": "哎，跟您说个新鲜事，我们家音箱成精了。"},
        {"role": "B", "line": "哟，怎么个成精法？"},
        {"role": "A", "line": "我让它关灯，它给我放了一首《好运来》。"},
        {"role": "B", "line": "嗐，那是它比你懂生活。"},
        {"role": "A", "line": "我一气之下把它拆了，您猜怎么着？"},
        {"role": "B", "line": "怎么着？"},
        {"role": "A", "line": "拆完发现，遥控器电池装反了。"},
        {"role": "B", "line": "好嘛，成精的是您呐！"},
    ]

    INTERACT = ["谢谢捧场，咱接着来～", "好嘞，您就是衣食父母～",
                "这掌声先记账上，散场一并谢～"]

    def interact_reply(self, brain):
        return self.INTERACT[self._pos % len(self.INTERACT)]

    def stage_strategies(self):
        return {
            "warmup": StageStrategy("warmup", 0.8, 0, "playful"),
            "explain": StageStrategy("explain", 0.4, 0, "witty"),
            "closing": StageStrategy("closing", 0.5, 0, "witty"),
            "valley": StageStrategy("valley", 0.8, 0, "playful"),
        }

    def __init__(self):
        self._pos = 0
        self.script = list(self.SCRIPT)    # 可被 --data 装载覆盖
        self._user_content = False
        self._last_role = "B"              # 轮转基准：下一位该 A

    async def proactive(self, brain):
        if (brain.settings.creative_llm and not self._user_content):
            role = "B" if self._last_role == "A" else "A"
            recent = "".join(
                r.spoken_text for r in brain.speech_results[-3:])
            lines = await CreativeWriter(brain).generate(
                "crosstalk",
                "当前该 %s（%s）说。最近对词：%s。请续写 %s 的下一句。" % (
                    role, "逗哏" if role == "A" else "捧哏",
                    recent[-80:] or "刚开场垫话", role),
                sentences=1)
            if lines:
                self._last_role = role
                emotion = "playful" if role == "A" else "steady"
                return build_task(
                    ["%s：%s" % (role, lines[0])],
                    source="format:crosstalk_ai", origin="AI对词",
                    emotion=emotion, clock=brain.clock)
        beat = self.script[self._pos % len(self.script)]
        self._pos += 1
        self._last_role = beat["role"]
        emotion = "playful" if beat["role"] == "A" else "steady"
        return build_task(
            [("%s：%s" % (beat["role"], beat["line"]))],
            source="format:crosstalk", origin="对词:%d" % self._pos,
            emotion=emotion, clock=brain.clock)

    def view(self, brain):
        next_role = "B" if self._last_role == "A" else "A"
        # 对词循环使用，进度按本轮位置显示（避免无限累加越界）
        pos = (self._pos - 1) % len(self.script) + 1 if self._pos else 0
        return {"对词进度": "%d/%d" % (pos, len(self.script)),
                "下一棒": "%s（%s）" % (next_role, "逗哏" if next_role == "A" else "捧哏"),
                "内容来源": "用户对词本" if self._user_content else "AI 续写+内置"}

    def handle_joke_request(self, brain, text, user_id):
        """相声场的"来一段/返场"：续演对词（同步路径，走内置脚本）。"""
        beat = self.script[self._pos % len(self.script)]
        self._pos += 1
        self._last_role = beat["role"]
        emotion = "playful" if beat["role"] == "A" else "steady"
        return build_task(
            [("%s：%s" % (beat["role"], beat["line"]))],
            source="format:crosstalk", origin="对词:%d" % self._pos,
            emotion=emotion, clock=brain.clock)


for _cls in (EcommerceFormat, ChatFormat, MusicFormat, StandupFormat,
             CrosstalkFormat):
    register(_cls)
