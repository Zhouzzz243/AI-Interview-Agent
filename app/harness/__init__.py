"""
Harness 层 — Agent 基础设施

【设计理念】
Harness 层是 Agent 的"安全网"和"仪表盘"，把横切关注点从编排层抽离：
- Budget: 预算控制，防烧钱/死循环
- Guard:  输出校验，防异常状态/幻觉
- Retry:  指数退避重试，提升可用性
- Trace:  全链路追踪，出了问题能定位
- Checkpoint: 断点恢复，用户刷新不丢状态

【目录结构】
app/harness/
├── __init__.py
├── budget.py      # 三层预算（Round/Turn/Session）
├── guard.py       # 三层校验（白名单/参数/降级）
├── retry.py       # 指数退避 + 错误分类
├── trace.py       # 链路追踪（span/trace/tag）✅
└── checkpoint.py  # 断点恢复（状态快照/恢复校验）✅

【Java 类比】
类似 Spring Boot 的 Filter/Interceptor 链，或者 Resilience4j 的
CircuitBreaker + RateLimiter + Retry 组合。
"""
