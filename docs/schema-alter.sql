-- ============================================================
-- AI面试Agent - 数据库增量更新脚本（已有表追加字段）
-- 执行方式：直接在MySQL中运行即可，不影响现有数据
-- ============================================================

USE `ai_interview`;

-- ============================================================
-- interview_session 表：新增评分相关字段
-- ============================================================

ALTER TABLE `interview_session`
    ADD COLUMN `final_score` INT DEFAULT NULL COMMENT '最终综合评分（0-100分，面试结束时由Python AI返回）'
    AFTER `end_time`;

ALTER TABLE `interview_session`
    ADD COLUMN `level` VARCHAR(2) DEFAULT NULL COMMENT '面试等级：A(>=85优秀) B(70-84良好) C(60-69合格) D(<60不合格)'
    AFTER `final_score`;

ALTER TABLE `interview_session`
    ADD COLUMN `dimension_scores` TEXT DEFAULT NULL COMMENT '各维度得分JSON（5维度加权）：{"practice_experience":85,"technical_knowledge":78,"communication":72,"potential":80,"attitude":75}'
    AFTER `level`;

ALTER TABLE `interview_session`
    ADD COLUMN `duration_minutes` INT DEFAULT NULL COMMENT '面试总时长（分钟）'
    AFTER `dimension_scores`;

-- 新增索引：加速排行榜查询
ALTER TABLE `interview_session`
    ADD INDEX `idx_final_score` (`final_score`);

-- ============================================================
-- 验证语句（执行后可运行此条确认字段已添加）
-- ============================================================
-- DESCRIBE `interview_session`;
-- SHOW INDEX FROM `interview_session`;

SELECT '✅ 增量更新完成！interview_session 表已新增5个字段 + 1个索引' AS message;
