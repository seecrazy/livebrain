-- LiveBrain M2 数据层 DDL（PostgreSQL 15+ / pgvector）
-- 内存实现（livebrain.data.product_store / knowledge_store / audit）的
-- 接口平移目标：表结构一一对应，切换时零决策层改动。
-- 应用：psql "$DATABASE_URL" -f deploy/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- 商品库
-- 数字的单一事实来源；价格一律用「分」（整数），杜绝浮点误差（DESIGN §8.1）
CREATE TABLE IF NOT EXISTS products (
    sku              TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    category         TEXT NOT NULL,              -- food / beauty / supplement ...
    price_cents      INTEGER NOT NULL CHECK (price_cents >= 0),
    orig_price_cents INTEGER NOT NULL,
    stock            INTEGER NOT NULL CHECK (stock >= 0),
    total_stock      INTEGER NOT NULL CHECK (total_stock > 0),
    ship_days        INTEGER NOT NULL,
    qual_flags       TEXT[] NOT NULL DEFAULT '{}',   -- 如 {'blue_hat'}
    version          BIGINT NOT NULL DEFAULT 1,      -- 快照版本（新鲜度校验 R12）
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 优惠叠加规则：按 priority 声明顺序应用（规则引擎促销计算器）
CREATE TABLE IF NOT EXISTS coupon_rules (
    id              BIGSERIAL PRIMARY KEY,
    sku             TEXT NOT NULL REFERENCES products(sku),
    rule_type       TEXT NOT NULL CHECK (rule_type IN ('full_cut', 'coupon')),
    threshold_cents INTEGER NOT NULL DEFAULT 0,
    cut_cents       INTEGER NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_coupon_rules_sku ON coupon_rules(sku, priority);

-- ---------------------------------------------------------------- 知识库
-- 卖点 / FAQ / 售后；embedding 维度随所选模型调整（如 bge-m3 = 1024）
CREATE TABLE IF NOT EXISTS knowledge_docs (
    doc_id    TEXT PRIMARY KEY,
    sku       TEXT NOT NULL DEFAULT '',          -- '' 表示全店通用
    text      TEXT NOT NULL,
    keywords  TEXT[] NOT NULL DEFAULT '{}',
    embedding vector(1024),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_sku ON knowledge_docs(sku);
CREATE INDEX IF NOT EXISTS idx_knowledge_keywords ON knowledge_docs USING gin(keywords);
-- 向量检索（M2 启用）：
-- CREATE INDEX IF NOT EXISTS idx_knowledge_embedding
--     ON knowledge_docs USING hnsw(embedding vector_cosine_ops);

-- ---------------------------------------------------------------- 审计总线
-- 追加式（append-only）：哈希链校验由应用层 AuditLog.verify() 执行，
-- 数据库层建议再授予只写权限并开启行级安全策略（生产加固项）
CREATE TABLE IF NOT EXISTS audit_entries (
    seq        BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL,
    type       TEXT NOT NULL,                    -- utterance/quarantine/promise/...
    room_id    TEXT NOT NULL,
    payload    JSONB NOT NULL,
    prev_hash  CHAR(64) NOT NULL,
    entry_hash CHAR(64) NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_room_time ON audit_entries(room_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_entries(type) WHERE type IN
    ('quarantine', 'promise', 'judgment', 'takeover', 'human_ops');
