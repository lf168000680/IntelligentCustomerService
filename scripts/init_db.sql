-- Kefu 初始化数据库脚本
-- 在 PostgreSQL 容器首次启动时自动执行

-- 启用扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 创建索引 (表由 SQLAlchemy 自动创建)
