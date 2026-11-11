# 播控大脑（LiveBrain）V4.1

**仿真人直播经营智能体 · 自研编排核心（M1）**

完整设计见 [DESIGN.md](DESIGN.md)（V4.1 整改版，含 V4.0→V4.1 全部整改对照表）。
路线图见 [ROADMAP.md](ROADMAP.md)。

## M1 是什么

按 V4.1 设计落地的**决策核心垂直切片**：五层三总线全部就位，全 Provider 可 Mock，
零第三方依赖即可端到端跑通模拟直播间，80 个测试全绿。

一条命令看完整演示（注入攻击/敏感拦截/幻觉拦截/承诺核销/判罚升级/降级切换/打断）：

```bash
python3 demo/run_demo.py
```

## 快速开始

```bash
# 测试（80 个）
python3 -m pytest tests/ -q

# 模拟直播间演示（输出审计日志到 demo/audit_demo.jsonl）
python3 demo/run_demo.py
```

仅依赖 Python 3.9+ 标准库；pytest 仅测试需要。

## 核心机制一览（对应 DESIGN.md 章节）

| 机制 | 模块 | 一句话 |
|---|---|---|
| 填槽制（§6.3） | `decision/slots.py` | LLM 只输出 `{price}` 占位符，数字在生成后填入，幻觉数字零出稿 |
| 三轨决策（§6.2） | `orchestrator.py` | 快轨规则 <500ms 绕过 LLM；中轨 RAG 2–4s；超时落兜底 |
| 弹幕消毒（§5.2） | `perception/sanitizer.py` | 注入弹幕隔离，永不进入 LLM |
| 滑动窗口聚合（§5.4） | `perception/aggregator.py` | 同题合并一次答，回复率预算抗洪峰 |
| 话术原子+承诺队列（§6.6） | `decision/atoms.py` | 上链接类话术自带 ops 副作用，说出口必核销 |
| 品类宣称引擎（§6.5） | `decision/filters.py` | 食品禁功效宣称、保健需蓝帽子旗标 |
| 场控状态机（§6.8） | `decision/field_controller.py` | 暖场/讲解/逼单/低谷，滞回切换 |
| 流式管线与打断（§7.4） | `execution/pipeline.py` | 50ms 音频淡出 + 250ms 视觉过渡 |
| 合规标识门禁（§7.3） | `execution/compliance.py` | 标识未武装，一帧都不出 |
| 降级链熔断（§7.5） | `execution/degradation.py` | provider 失败计数熔断自动切换，审计可回滚 |
| 审计哈希链（§8.3） | `data/audit.py` | AI 话术+人工操作追加式记录，verify 可证未篡改 |
| 人工接管/交回（§7.6） | `ops/takeover.py` | 热键静默，交回需清点未核销承诺 |

## 目录结构

```
livebrain/
├── orchestrator.py        编排器 LiveBrain（三轨路由/判罚升级/打断调度/承诺核销）
├── perception/            消毒 / 分类 / 聚合与回复率
├── decision/              填槽 / 规则引擎 / LLM中轨 / 原子承诺 / 过滤 / 场控 / 人设 / 兜底
├── execution/             TTS / 渲染 / 合规门禁 / 流式管线 / 降级链
├── data/                  商品库 / 知识库 / 会话 / 审计哈希链
├── platform/              模拟平台适配器（判罚信号 / 运营动作）
└── ops/                   人工接管与交回
tests/                     12 个测试文件（单元 + 端到端模拟）
demo/run_demo.py           模拟直播间演示
DESIGN.md                  V4.1 完整设计
ROADMAP.md                 M1–M4 里程碑
```

## M2 接入真实能力

- LLM：`decision/llm_agent.py` 的 `LLMProvider` 接口对接 OpenAI 兼容端点（如火山方舟）
- TTS：`execution/tts.py` 追加商用授权 Provider（Edge TTS 仅验证期/预合成，不入商用链）
- 渲染：`execution/renderer.py` 追加 MuseTalk / SoulX Provider
- 数据层：`data/product_store.py`、`data/knowledge_store.py` 平移 PostgreSQL + pgvector
