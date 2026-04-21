-- ============================================================
-- AI面试Agent - 数据库增量更新脚本 v3.0（最终版）
-- 执行方式：在MySQL中运行，追加v3文档要求的所有缺失字段
-- 日期：2026-04-16
-- ============================================================

USE `ai_interview`;

-- ============================================================
-- 一、interview_session 表：追加 summary 和 suggestions 字段
-- 【来源】JAVA_PYTHON_ALIGN_v3.md 第三节
-- ============================================================

ALTER TABLE `interview_session`
    ADD COLUMN `summary` TEXT DEFAULT NULL COMMENT 'AI综合评语(Python end接口返回)'
    AFTER `dimension_scores`;

ALTER TABLE `interview_session`
    ADD COLUMN `suggestions` TEXT DEFAULT NULL COMMENT '改进建议JSON数组(JSON字符串格式)'
    AFTER `summary`;

-- ============================================================
-- 二、interview_message 表：追加 question_type/phase/is_follow_up 字段
-- 【来源】JAVA_PYTHON_ALIGN_v3.md 第三节
-- 【用途】前端按题目类型、阶段、是否追问进行筛选展示
-- ============================================================

ALTER TABLE `interview_message`
    ADD COLUMN `question_type` VARCHAR(32) DEFAULT NULL COMMENT '题目分类(self_introduction/internship/project/technical_javase/technical_jvm/technical_juc/technical_spring/technical_mysql/technical_redis/technical_mq/technical_network/chat/reverse_question)'
    AFTER `score`;

ALTER TABLE `interview_message`
    ADD COLUMN `phase` VARCHAR(32) DEFAULT NULL COMMENT '面试阶段(self_introduction/internship_qa/project_qa/eight_part_qa/chat_mode/final_score/end)'
    AFTER `question_type`;

ALTER TABLE `interview_message`
    ADD COLUMN `is_follow_up` TINYINT DEFAULT NULL COMMENT '是否追问(0=否 1=是 NULL=非问答消息如闲聊/系统提示)'
    AFTER `phase`;

-- ============================================================
-- 三、验证语句（执行后可运行此条确认字段已添加）
-- ============================================================
-- DESCRIBE `interview_session`;
-- DESCRIBE `interview_message`;

SELECT '✅ DDL增量更新v3.0完成！' AS message;
SELECT '  - interview_session表新增: summary, suggestions (共2个字段)' AS details1;
SELECT '  - interview_message表新增: question_type, phase, is_follow_up (共3个字段)' AS details2;
SELECT '  - 总计新增5个字段，与v3文档完全对齐' AS summary;
