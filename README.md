# 播控大脑 LiveBrain

**仿真人直播经营智能体 · V4.1 整改版 · 自研编排核心**

人机协同的直播经营智能体：AI 负责讲解、互动、节奏调控与合规兜底，人工负责异常接管与策略审核。**合规是入场券，规则引擎是信任底线，打断响应是体验底线。**

| | |
|---|---|
| 设计文档 | [DESIGN.md](DESIGN.md)（V4.2 完整设计：R1–R14 整改 + V1–V4 增补，9 张架构图） |
| 项目进度 | [PROGRESS.md](PROGRESS.md)（里程碑总览 / V4.2 明细 / 质量指标 / 风险看板 / 变更日志） |
| 路线图 | [ROADMAP.md](ROADMAP.md)（M1–M4 验收标准） |
| 当前状态 | **M1 已交付 · M2 代码完成 · V4.2 混播+形象资产已交付**：117 测试全绿，零运行时依赖（Python 3.9+） |

## 架构一图流

```mermaid
flowchart TB
    subgraph AC["接入层 platform"]
        PA["平台适配器＋compliance profile<br/>报备 · 标识规格 · 判罚信号"]
    end
    subgraph PE["感知层 perception"]
        BUS{{"事件总线（优先级堆）"}}
        SAN["弹幕消毒<br/>注入隔离"]
        AGG["滑动窗口聚合<br/>＋回复率预算"]
    end
    subgraph DE["决策层 decision"]
        ORCH["编排器 LiveBrain"]
        FAST["快轨 规则引擎<br/>＜500ms · 绕过 LLM"]
        MID["中轨 RAG＋LLM<br/>填槽＋回检 2–4s"]
        AT["话术原子＋承诺队列"]
    end
    subgraph EX["执行层 execution"]
        PIPE["流式管线＋AI 标识门禁<br/>打断协议 50ms/250ms"]
        DEG["降级链＋熔断器"]
    end
    subgraph DA["数据层 data"]
        AU[("审计哈希链<br/>可证明未篡改")]
    end
    PA --> BUS --> SAN --> AGG --> ORCH
    ORCH --> FAST --> PIPE
    ORCH --> MID --> PIPE
    ORCH --> AT -->|运营动作| PA
    DEG -.-> MID
    PIPE -.-> AU
    classDef acL fill:#e3f2fd,stroke:#1976d2,color:#0d47a1,stroke-width:2px
    classDef peL fill:#fff8e1,stroke:#f9a825,color:#5d4037,stroke-width:2px
    classDef deL fill:#e8f5e9,stroke:#388e3c,color:#1b5e20,stroke-width:2px
    classDef exL fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c,stroke-width:2px
    classDef daL fill:#fce4ec,stroke:#c2185b,color:#880e4f,stroke-width:2px
    class PA acL
    class BUS,SAN,AGG peL
    class ORCH,FAST,MID,AT deL
    class PIPE,DEG exL
    class AU daL
```

## 快速开始

```bash
# 全量测试（117 个，离线可跑）
python3 -m pytest tests/ -q

# 模拟直播间演示：注入攻击/敏感拦截/幻觉拦截/承诺核销/判罚升级/降级切换/打断
python3 demo/run_demo.py

# 回放测试工具（CI 可用：违反不变量则退出码 1）
python3 tools/replay.py record --out /tmp/session.jsonl
python3 tools/replay.py check  --in  /tmp/session.jsonl
```

仅依赖 Python 3.9+ 标准库；`edge-tts` 为可选依赖（验证期 TTS）；pytest 仅测试需要。

## 直播形态支持（V4.2）

| 形态 | 支持 | 说明 |
|---|---|---|
| 数字人主播 | ✅ | 渲染 Provider 架构（MuseTalk/SoulX M3 实装），persona 绑定表情基线 |
| 真人接管 | ✅ M1 已交付 | 热键静默 + 承诺清点 + 状态摘要，全程审计 |
| AI+真人混播 | ✅ V4.2 已交付 | 排班器时段切换 + 真人采集通道 + 交叉淡化画面切换 + 标识跟随内容源 + 切回承诺门 |
| 形象资产管理 | ✅ V4.2 已交付 | 真人底模肖像授权校验 + 平台报备绑定，未过审拒绝开播 |
| 多直播间 | ✅ | 每间一个 LiveBrain 实例（GPU 池调度 M3） |
| 单间双主播 | 🔶 设计就绪 | 多 persona 并行/双话术通道/轮转策略（DESIGN §10.1，实施 M3） |

## 信任四件套（与竞品的本质差异）

1. **填槽制**：LLM 只输出 `{price}` 占位符，数字在生成后由规则引擎填入——幻觉数字在机制上不可能出稿（测试断言 "199" 永不出现）。
2. **话术原子＋承诺队列**："上链接"类话术自带运营动作副作用，说出口必核销，AI 永不开空头支票；自由文本承诺词（保证/秒发/假一赔十）一律拦截。
3. **弹幕消毒**：直播是公开对抗输入场，注入弹幕隔离后永不进入 LLM（40 条红队集全量回归）。
4. **审计哈希链**：AI 话术＋人工操作＋帧检查点全部追加式入链，`verify()` 可定位任意事后篡改。

## 目录结构

```
livebrain/            核心包（30 模块）
├── orchestrator.py     编排器：三轨路由/判罚升级/打断调度/承诺核销/filler/混播切换
├── perception/         消毒（注入隔离）/ 意图分类 / 聚合与回复率预算
├── decision/           填槽 / 规则引擎 / LLM中轨 / 原子承诺 / 过滤 / 场控 / 人设 / 兜底池
├── execution/          TTS（Mock+EdgeTTS）/ LLM（OpenAI兼容）/ 渲染 / 合规门禁 / 流式管线 / 熔断降级链
├── mixed/              混播引擎：排班器 + 真人采集通道（V4.2）
├── data/               商品库 / 形象资产（授权/报备）/ 知识库 / 会话 / 审计哈希链
├── platform/           模拟平台（判罚信号/运营动作/真人采集/形象绑定）
├── ops/                人工接管与交回
└── scenarios.py        演示与回放共用剧本
assets/                 红队弹幕集（40 条，回归资产）
tools/replay.py         回放测试工具（四不变量校验）
deploy/                 PG+pgvector DDL / docker-compose / 配置样例
tests/                  19 文件 117 用例
demo/                   全场景演示
```

## 接入真实能力（M2 联调指引）

| 能力 | 入口 | 说明 |
|---|---|---|
| LLM | `execution/llm_openai_compat.py` | 任意 OpenAI 兼容端点（火山方舟/DeepSeek/vLLM），凭据走环境变量 `ARK_API_KEY` |
| TTS | `execution/tts.py` | EdgeTTS 仅验证期/预合成；商用实时链路须接有授权的流式 TTS |
| 渲染 | `execution/renderer.py` | MuseTalk/SoulX Provider（需 GPU），打断过渡段接口已定义 |
| 数据层 | `deploy/schema.sql` | PG+pgvector DDL 与内存实现一一对应，切换零决策层改动 |

## 合规内建（不可绕过）

显著 AI 标识门禁（未武装不出帧；混播下标识跟随内容源）· 开播报备前置校验 · **形象授权门禁（真人底模无授权/过期拒绝开播）** · 禁纯无人形态 · 兜底话术池防"机械重复录播"判定 · 人工接管热键与交回承诺清点 · 全量操作审计。详见 [DESIGN.md](DESIGN.md) 第 2、7.7、8.6 章。
