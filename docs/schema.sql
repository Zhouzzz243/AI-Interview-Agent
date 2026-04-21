-- ============================================================
-- AI面试Agent - 数据库建表脚本
-- 数据库：MySQL 8.0+
-- 字符集：utf8mb4（支持中文、emoji）
-- ============================================================

-- 如果数据库不存在则创建
CREATE DATABASE IF NOT EXISTS `ai_interview`
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_general_ci;

USE `ai_interview`;

-- ============================================================
-- 1. 用户表（简化版，企业级规范）
-- ============================================================
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '用户ID（主键自增）',
    `username` VARCHAR(64) NOT NULL COMMENT '用户名（登录账号，唯一）',
    `password` VARCHAR(128) NOT NULL COMMENT '密码（BCrypt加密存储，绝对不存明文）',
    `is_deleted` TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除标记：0-未删除，1-已删除',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_username` (`username`) COMMENT '用户名唯一索引'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户信息表';

-- ============================================================
-- 2. 简历表（企业级：逻辑删除+索引+字段注释+大文本类型）
-- ============================================================
DROP TABLE IF EXISTS `resume`;
CREATE TABLE `resume` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '简历ID（主键自增）',
    `user_id` BIGINT NOT NULL COMMENT '用户ID（关联user表）',
    `file_name` VARCHAR(255) NOT NULL COMMENT '简历原始文件名（例如：张三_Java工程师.pdf）',
    `file_url` VARCHAR(512) NOT NULL COMMENT '简历存储路径（服务器本地绝对路径）',
    `parse_status` TINYINT NOT NULL DEFAULT 0 COMMENT '解析状态：0-待解析，1-解析中，2-解析成功，3-解析失败',
    `parsed_content` TEXT COMMENT 'AI解析后的简历内容（JSON格式字符串）',
    `is_deleted` TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除：0-未删，1-已删',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_user_id` (`user_id`) COMMENT '用户ID索引（加速按用户查询简历）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='简历信息表';

-- ============================================================
-- 3. 面试会话表（企业级：事务安全+复合索引）
-- ============================================================
DROP TABLE IF EXISTS `interview_session`;
CREATE TABLE `interview_session` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '面试会话ID（主键自增）',
    `user_id` BIGINT NOT NULL COMMENT '用户ID（谁在面试）',
    `resume_id` BIGINT NOT NULL COMMENT '简历ID（用哪份简历面试）',
    `status` TINYINT NOT NULL DEFAULT 0 COMMENT '会话状态：0-进行中，1-已结束，2-异常终止',
    `start_time` DATETIME DEFAULT NULL COMMENT '面试开始时间',
    `end_time` DATETIME DEFAULT NULL COMMENT '面试结束时间',
    `final_score` INT DEFAULT NULL COMMENT '最终综合评分（0-100分，面试结束时由Python AI返回）',
    `level` VARCHAR(2) DEFAULT NULL COMMENT '面试等级：A(>=85优秀) B(70-84良好) C(60-69合格) D(<60不合格)',
    `dimension_scores` TEXT DEFAULT NULL COMMENT '各维度得分JSON（5维度加权）：{"practice_experience":85,"technical_knowledge":78,"communication":72,"potential":80,"attitude":75}',
    `duration_minutes` INT DEFAULT NULL COMMENT '面试总时长（分钟）',
    `is_deleted` TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除：0-未删，1-已删',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_resume_id` (`resume_id`) COMMENT '简历ID索引',
    KEY `idx_user_id` (`user_id`) COMMENT '用户ID索引',
    KEY `idx_final_score` (`final_score`) COMMENT '评分索引（排行榜查询用）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI面试会话表';

-- ============================================================
-- 4. 面试消息表（企业级：评分字段+会话索引）
-- ============================================================
DROP TABLE IF EXISTS `interview_message`;
CREATE TABLE `interview_message` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '消息ID（主键自增）',
    `session_id` BIGINT NOT NULL COMMENT '所属会话ID（关联interview_session表）',
    `role` VARCHAR(32) NOT NULL COMMENT '角色：interviewer-面试官(AI)，interviewee-面试者(用户)',
    `content` TEXT NOT NULL COMMENT '对话内容（问题或回答）',
    `score` TINYINT DEFAULT NULL COMMENT 'AI评分（0-100分，仅面试者的回答有分数）',
    `is_deleted` TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除：0-未删，1-已删',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（消息发送时间）',
    PRIMARY KEY (`id`),
    KEY `idx_session_id` (`session_id`) COMMENT '会话ID索引（加速查询某场面试的所有对话）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='面试对话消息表';

-- ============================================================
-- 5. 资讯/文章表（页面展示用）
-- ============================================================
DROP TABLE IF EXISTS `news`;
CREATE TABLE `news` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '资讯ID（主键自增）',
    `title` VARCHAR(255) NOT NULL COMMENT '文章标题',
    `cover_url` VARCHAR(512) DEFAULT NULL COMMENT '封面图URL',
    `content` TEXT NOT NULL COMMENT '文章正文（支持HTML富文本格式）',
    `sort` INT DEFAULT 0 COMMENT '排序权重（数字越小越靠前）',
    `status` TINYINT DEFAULT 1 COMMENT '启用状态：1-启用（前端展示），0-禁用（下架/草稿）',
    `is_deleted` TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除：0-未删，1-已删',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='资讯视图表';

-- ============================================================
-- 插入测试数据（可选，用于开发调试）
-- ============================================================

-- 插入测试用户（密码是123456的BCrypt密文）
INSERT INTO `user` (username, password) VALUES
('testuser', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8l9l7lE6s5e4K8c3m2');

-- 插入测试资讯
INSERT INTO `news` (title, content, sort, status) VALUES
('2024年Java面试必考知识点', '<h3>核心考点</h3><p>1. Java基础...</p><p>2. 集合框架...</p>', 1, 1),
('Spring Boot最佳实践', '<h3>实战技巧</h3><p>1. 自动配置原理...</p>', 2, 1),
('MySQL性能优化指南', '<h3>优化策略</h3><p>1. 索引优化...</p>', 3, 1);

-- ============================================================
-- 建表完成提示
-- ============================================================
SELECT '✅ 数据库建表完成！共创建5张表：user, resume, interview_session, interview_message, news' AS message;
