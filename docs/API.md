# API 概览

默认地址：`http://127.0.0.1:8000`。交互式文档：`/docs`。

## 运行信息

- `GET /api/health`：服务健康与版本；
- `GET /api/meta`：运行环境、数据模式与只读状态。
- `GET /api/meta/enums`：前后端共用的状态枚举。

## 来源与导入

- `GET /api/sources`：来源聚合；
- `GET /api/sources/batches`：导入批次；
- `POST /api/sources/preview`：解析预览，不写数据库；
- `POST /api/sources/import`：确认导入并物化。
- `GET /api/sources/connectors`：已保存的远程来源及最近同步状态；
- `POST /api/sources/connectors/feishu/preview`：解析飞书 URL，通过官方 API 全量分页后返回预览，不写入；
- `POST /api/sources/connectors/feishu`：保存 table/view 连接并生成首个不可变快照；
- `POST /api/sources/{source_id}/sync`：立即全量同步并返回新增、修改、缺失和未变计数；
- `GET /api/sources/sync-runs`：远程同步历史及失败原因。
- `GET /api/sources/sync-runs/{run_id}/changes`：按记录 ID 读取完整新增、修改或缺失明细（支持 `change_type/limit/offset`）。

## 岗位与证据

- `GET /api/opportunities`：分页、搜索，以及城市、届次、招聘批次、企业性质、笔试要求、截止窗口、三轴和冲突筛选；支持按更新时间或截止时间排序；
- `GET /api/opportunities/{id}`：Raw origin、Claim、Verification 与 Decision history；
- `PATCH /api/opportunities/{id}/classification`：人工纠正 Campaign / Posting；
- `PATCH /api/opportunities/{id}/official-domain`：确认公司官方招聘域与 ATS scope；
- `PATCH /api/opportunities/{id}/official-identity`：绑定官方岗位 ID；
- `POST /api/opportunities/{id}/verifications`：保存人工辅助官网核验；
- `POST /api/opportunities/{campaign_id}/postings`：关联同公司的 Campaign 与 Posting；
- `GET /api/opportunities/review/duplicates`：按状态限量读取待处理的重复候选；
- `PATCH /api/opportunities/review/duplicates/{candidate_id}`：处理重复候选。
- `PATCH /api/opportunities/{id}/decision`：保存带理由的人工决策。

## 画像与决策

- `GET /api/workspace/profile`：已确认事实与偏好；
- `POST /api/workspace/profile/extract`：从粘贴的简历文本抽取候选事实；
- `POST /api/workspace/profile/upload`：上传 TXT / Markdown / PDF 并抽取候选事实；
- `PATCH /api/workspace/profile/facts/{id}`：确认或纠正事实；
- `PUT /api/workspace/profile/preferences/{key}`：维护硬约束与偏好；
- `DELETE /api/workspace/profile`：删除画像、偏好与派生决策；
- `POST /api/workspace/decisions/recompute`：重算三轴。
- `GET /api/workspace/dashboard`：今日决策概览与一致的队列计数；
- `GET /api/workspace/decision-queue?queue=ready|verify_first`：分页读取可直接投或优先核验队列。

## 可信投递计划

- `GET /api/workspace/shortlist`：含 ready 与 blockers；
- `POST /api/workspace/shortlist/{id}`：通过服务端门禁后加入；
- `PATCH /api/workspace/shortlist/{id}/application`：更新待投递、已投递、笔试/测评、面试、Offer 等阶段及下一步行动；
- `DELETE /api/workspace/shortlist/{id}`：移除；
- `GET /api/workspace/shortlist/export?format=csv|json|markdown`：只导出 ready 记录。

## 评测

- `GET /api/evaluation/summary`：公开安全的聚合评测；
- `GET /api/evaluation/report`：自包含 HTML 报告。

## 安全语义

`public-demo` 对所有非 GET/HEAD/OPTIONS 请求返回 403。所有影响投递的写操作都在服务端校验，不依赖前端隐藏按钮。
