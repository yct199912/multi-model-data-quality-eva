-- infra/docker/postgres/init.sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
--  评价任务表
-- ============================================================
CREATE TABLE IF NOT EXISTS eval_tasks (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID UNIQUE DEFAULT gen_random_uuid(),
    user_name       VARCHAR(128) NOT NULL,
    repo_name       VARCHAR(256) NOT NULL,
    branch_name     VARCHAR(128) DEFAULT 'master',
    repo_introduction TEXT,
    status          VARCHAR(16) DEFAULT 'pending',
    total_files     INTEGER DEFAULT 0,
    evaluated_files INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER
);

CREATE INDEX idx_eval_tasks_status ON eval_tasks(status);
CREATE INDEX idx_eval_tasks_user_repo ON eval_tasks(user_name, repo_name);

-- ============================================================
--  准确性得分表 (content_accuracy_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS content_accuracy_score (
    id          BIGSERIAL PRIMARY KEY,
    repo        VARCHAR(255) NOT NULL,
    file_path   VARCHAR(255) NOT NULL,
    score       NUMERIC(10, 2),
    file_type   VARCHAR(10) NOT NULL,  -- image / text
    eva_dsc     TEXT,
    deleted     INT2 DEFAULT 0,
    eva_type    VARCHAR(20) NOT NULL,   -- image-content / text-format / text-content
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_accuracy_repo ON content_accuracy_score(repo);
CREATE INDEX idx_accuracy_file ON content_accuracy_score(file_path);
CREATE INDEX idx_accuracy_type ON content_accuracy_score(file_type, eva_type);

-- ============================================================
--  完整性得分表 (content_consistency_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS content_consistency_score (
    id          BIGSERIAL PRIMARY KEY,
    repo        VARCHAR(255) NOT NULL,
    file_path   VARCHAR(255) NOT NULL,
    score       NUMERIC(10, 2),
    file_type   VARCHAR(10) NOT NULL,  -- image / text
    eva_dsc     TEXT,
    deleted     INT2 DEFAULT 0,
    eva_type    VARCHAR(20) NOT NULL,   -- image-noinfo / image-noise / text-noinfo / text-desc
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_consistency_repo ON content_consistency_score(repo);
CREATE INDEX idx_consistency_file ON content_consistency_score(file_path);
CREATE INDEX idx_consistency_type ON content_consistency_score(file_type, eva_type);

-- ============================================================
--  唯一性得分表 (content_unq_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS content_unq_score (
    id          BIGSERIAL PRIMARY KEY,
    repo        VARCHAR(255) NOT NULL,
    file_path   VARCHAR(255) NOT NULL,
    score       NUMERIC(10, 2),
    file_type   VARCHAR(10) NOT NULL,  -- image / text
    eva_dsc     TEXT,
    deleted     INT2 DEFAULT 0,
    eva_type    VARCHAR(20) NOT NULL,   -- image-content / text-content
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_unq_repo ON content_unq_score(repo);
CREATE INDEX idx_unq_file ON content_unq_score(file_path);
CREATE INDEX idx_unq_type ON content_unq_score(file_type, eva_type);

-- ============================================================
--  一致性得分表 (content_integrity_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS content_integrity_score (
    id          BIGSERIAL PRIMARY KEY,
    repo        VARCHAR(255) NOT NULL,
    file_path   VARCHAR(255) NOT NULL,
    score       NUMERIC(10, 2),
    file_type   VARCHAR(10) NOT NULL,  -- image / text
    eva_dsc     TEXT,
    deleted     INT2 DEFAULT 0,
    eva_type    VARCHAR(20) NOT NULL,   -- image-content / text-content
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_integrity_repo ON content_integrity_score(repo);
CREATE INDEX idx_integrity_file ON content_integrity_score(file_path);
CREATE INDEX idx_integrity_type ON content_integrity_score(file_type, eva_type);

-- ============================================================
--  单文件评价结果汇总表 (eval_file_results)
-- ============================================================
CREATE TABLE IF NOT EXISTS eval_file_results (
    id                      BIGSERIAL PRIMARY KEY,
    task_id                 UUID NOT NULL REFERENCES eval_tasks(task_id),
    user_name               VARCHAR(128) NOT NULL,
    repo_name               VARCHAR(256) NOT NULL,
    file_path               VARCHAR(255) NOT NULL,
    file_type               VARCHAR(10) NOT NULL,      -- image / text
    file_size               BIGINT DEFAULT 0,
    image_info_uniqueness   NUMERIC(10, 2),
    solid_region_score      NUMERIC(10, 2),
    noise_score             NUMERIC(10, 2),
    object_completeness     NUMERIC(10, 2),
    text_info_uniqueness    NUMERIC(10, 2),
    junk_score              NUMERIC(10, 2),
    desc_completeness       NUMERIC(10, 2),
    dataset_uniqueness      NUMERIC(10, 2),
    description             TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_file_results_task ON eval_file_results(task_id);
CREATE INDEX idx_file_results_type ON eval_file_results(file_type);

-- ============================================================
--  数据集级别聚合结果表 (eval_aggregate_results)
-- ============================================================
CREATE TABLE IF NOT EXISTS eval_aggregate_results (
    id                        BIGSERIAL PRIMARY KEY,
    task_id                    UUID UNIQUE NOT NULL REFERENCES eval_tasks(task_id),
    user_name                  VARCHAR(128) NOT NULL,
    repo_name                  VARCHAR(256) NOT NULL,
    branch_name                VARCHAR(128) DEFAULT 'master',
    total_image_count          INTEGER DEFAULT 0,
    total_text_count           INTEGER DEFAULT 0,
    unique_image_count         INTEGER DEFAULT 0,
    unique_text_count          INTEGER DEFAULT 0,
    image_uniqueness_score     NUMERIC(10, 2),
    image_completeness_score   NUMERIC(10, 2),
    text_uniqueness_score      NUMERIC(10, 2),
    text_completeness_score    NUMERIC(10, 2),
    image_uniqueness_description TEXT,
    text_uniqueness_description  TEXT,
    created_at                 TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agg_results_task ON eval_aggregate_results(task_id);

-- ============================================================
--  仓库级有效性得分表 (repo_effectiveness_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS repo_effectiveness_score (
    id          BIGSERIAL PRIMARY KEY,
    repo        VARCHAR(255) NOT NULL,
    score       NUMERIC(10, 2),
    eva_dsc     TEXT,
    eva_type    VARCHAR(30) NOT NULL DEFAULT 'repo-effectiveness',
    deleted     INT2 DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_effectiveness_repo ON repo_effectiveness_score(repo);

-- ============================================================
--  仓库级及时性得分表 (repo_timeliness_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS repo_timeliness_score (
    id          BIGSERIAL PRIMARY KEY,
    repo        VARCHAR(255) NOT NULL,
    score       NUMERIC(10, 2),
    eva_dsc     TEXT,
    eva_type    VARCHAR(30) NOT NULL DEFAULT 'repo-timeliness',
    deleted     INT2 DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_timeliness_repo ON repo_timeliness_score(repo);

-- ============================================================
--  仓库级唯一性得分表 (repo_unq_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS repo_unq_score (
    id              BIGSERIAL PRIMARY KEY,
    repo            VARCHAR(255) NOT NULL,
    score_model     NUMERIC(10, 2),          -- 模型评价得分
    eva_dsc         TEXT,                     -- 模型评价描述
    deleted         INT2 DEFAULT 0,
    eva_rule_type   VARCHAR(100) NOT NULL,    -- inter-image-unq / inter-text-unq / imgself-unq / textself-unq
    score_avg       NUMERIC(10, 2),          -- 所有文件该维度平均分
    score           NUMERIC(10, 2),           -- 加权得分
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_repo_unq_repo ON repo_unq_score(repo);
CREATE INDEX idx_repo_unq_rule ON repo_unq_score(eva_rule_type);

-- ============================================================
--  仓库级一致性得分表 (repo_integrity_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS repo_integrity_score (
    id              BIGSERIAL PRIMARY KEY,
    repo            VARCHAR(255) NOT NULL,
    score_model     NUMERIC(10, 2),          -- 模型评价得分
    eva_dsc         TEXT,                     -- 模型评价描述
    deleted         INT2 DEFAULT 0,
    eva_rule_type   VARCHAR(100) NOT NULL,   -- inter-image-integrity / inter-text-integrity / imgself-integrity / textself-integrity
    score_avg       NUMERIC(10, 2),          -- 所有文件该维度平均分
    score           NUMERIC(10, 2),           -- 加权得分
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_repo_integrity_repo ON repo_integrity_score(repo);
CREATE INDEX idx_repo_integrity_rule ON repo_integrity_score(eva_rule_type);

-- ============================================================
--  仓库级准确性得分表 (repo_accuracy_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS repo_accuracy_score (
    id              BIGSERIAL PRIMARY KEY,
    repo            VARCHAR(255) NOT NULL,
    score_model     NUMERIC(10, 2),          -- 模型评价得分
    eva_dsc         TEXT,                     -- 模型评价描述
    deleted         INT2 DEFAULT 0,
    eva_rule_type   VARCHAR(100) NOT NULL,   -- imgself-accuracy / textself-accuracy-format / textself-accuracy-content
    score_avg       NUMERIC(10, 2),          -- 所有文件该维度平均分
    score           NUMERIC(10, 2),           -- 加权得分
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_repo_accuracy_repo ON repo_accuracy_score(repo);
CREATE INDEX idx_repo_accuracy_rule ON repo_accuracy_score(eva_rule_type);

-- ============================================================
--  仓库级完整性得分表 (repo_consistency_score)
-- ============================================================
CREATE TABLE IF NOT EXISTS repo_consistency_score (
    id              BIGSERIAL PRIMARY KEY,
    repo            VARCHAR(255) NOT NULL,
    score_model     NUMERIC(10, 2),          -- 模型评价得分
    eva_dsc         TEXT,                     -- 模型评价描述
    deleted         INT2 DEFAULT 0,
    eva_rule_type   VARCHAR(100) NOT NULL,   -- imgself-consistency-region / imgself-consistency-noise / textself-consistency-noinfo / textself-consistency-content
    score_avg       NUMERIC(10, 2),          -- 所有文件该维度平均分
    score           NUMERIC(10, 2),           -- 加权得分
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_repo_consistency_repo ON repo_consistency_score(repo);
CREATE INDEX idx_repo_consistency_rule ON repo_consistency_score(eva_rule_type);

-- ============================================================
--  审计日志（保留）
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    VARCHAR(128) NOT NULL,
    action      VARCHAR(64) NOT NULL,
    resource    VARCHAR(512),
    details     JSONB,
    ip_address  INET,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);