# 校招岗位决策台可复现评测

- 生成时间：`2026-08-10T17:57:37.613597Z`
- 评测器：`evaluation-harness.v1`
- 数据库标识：`private-baseline`
- 数据库输出策略：仅聚合计数与比率，不输出任何岗位、公司、链接、简历或来源原文。

> 边界声明：全部 gold fixtures 都由开发者合成。经验性样本只是小型回归集，不是真实用户、企业、投递或面试数据，不支持任何录用率或线上准确率声称。

## 结论摘要

- Contract/boundary：**25 / 25** 通过。
- Heuristic sample：**8 / 8** 与人工标注一致；只代表本合成样本集。
- 私有基线结构：7919 条原始记录，7890 个机会实体，79648 条字段 claim。

## Gold fixture 结果

| 样本 | 集合 | 能力 | 期望 | 实际 | 结果 |
|---|---|---|---|---|---|
| `contract.classification.broad_campaign` | contract_boundary | campaign_posting_classification | `CAMPAIGN` | `CAMPAIGN` | 通过 |
| `contract.classification.official_posting` | contract_boundary | campaign_posting_classification | `POSTING` | `POSTING` | 通过 |
| `contract.classification.direct_posting` | contract_boundary | campaign_posting_classification | `POSTING` | `POSTING` | 通过 |
| `contract.dedup.official_id_conflict` | contract_boundary | duplicate_candidate_decision | `SEPARATE` | `SEPARATE` | 通过 |
| `contract.dedup.compound_hint_never_merges` | contract_boundary | duplicate_candidate_decision | `REVIEW` | `REVIEW` | 通过 |
| `contract.decision.verified_specific_posting` | contract_boundary | three_axis_decision_guardrail | `{"eligibility":"PASS","evidence_fit":"PRIMARY","trust":"VERIFIED"}` | `{"eligibility":"PASS","evidence_fit":"PRIMARY","trust":"VERIFIED"}` | 通过 |
| `contract.decision.campaign_not_eligible` | contract_boundary | three_axis_decision_guardrail | `{"eligibility":"UNKNOWN","trust":"CONSISTENT"}` | `{"eligibility":"UNKNOWN","trust":"CONSISTENT"}` | 通过 |
| `contract.decision.blocked_is_not_closed` | contract_boundary | three_axis_decision_guardrail | `{"eligibility":"UNKNOWN","trust":"UNKNOWN"}` | `{"eligibility":"UNKNOWN","trust":"UNKNOWN"}` | 通过 |
| `contract.decision.stale_official_evidence` | contract_boundary | three_axis_decision_guardrail | `{"trust":"STALE"}` | `{"trust":"STALE"}` | 通过 |
| `contract.decision.unconfirmed_resume_gets_no_credit` | contract_boundary | three_axis_decision_guardrail | `{"evidence_fit":"UNKNOWN"}` | `{"evidence_fit":"UNKNOWN"}` | 通过 |
| `contract.verification.accept_company_domain` | contract_boundary | official_domain_guardrail | `jobs.synthetic-example.com` | `jobs.synthetic-example.com` | 通过 |
| `contract.verification.reject_aggregator` | contract_boundary | official_domain_guardrail | `{"error":"聚合平台域名不能确认为公司官方招聘域名"}` | `{"error":"聚合平台域名不能确认为公司官方招聘域名"}` | 通过 |
| `contract.verification.reject_public_suffix` | contract_boundary | official_domain_guardrail | `{"error":"公共后缀或单标签不能作为官方招聘域名"}` | `{"error":"公共后缀或单标签不能作为官方招聘域名"}` | 通过 |
| `contract.verification.reject_ip_address` | contract_boundary | official_domain_guardrail | `{"error":"IP 地址不能作为官方招聘域名"}` | `{"error":"IP 地址不能作为官方招聘域名"}` | 通过 |
| `contract.verification.shared_ats_requires_tenant` | contract_boundary | official_domain_guardrail | `{"error":"共享 ATS 域名必须提供包含公司租户路径的招聘页面 URL"}` | `{"error":"共享 ATS 域名必须提供包含公司租户路径的招聘页面 URL"}` | 通过 |
| `contract.verification.reject_workday_parent_domain` | contract_boundary | official_domain_guardrail | `{"error":"共享 ATS 父域不能作为单家公司官网；请提供包含公司租户的招聘页面 URL"}` | `{"error":"共享 ATS 父域不能作为单家公司官网；请提供包含公司租户的招聘页面 URL"}` | 通过 |
| `contract.verification.reject_workday_infrastructure_domain` | contract_boundary | official_domain_guardrail | `{"error":"共享 ATS 父域不能作为单家公司官网；请提供包含公司租户的招聘页面 URL"}` | `{"error":"共享 ATS 父域不能作为单家公司官网；请提供包含公司租户的招聘页面 URL"}` | 通过 |
| `contract.verification.shared_ats_keeps_tenant_scope` | contract_boundary | official_domain_guardrail | `{"domain":"job-boards.greenhouse.io","scope_path":"/company-a"}` | `{"domain":"job-boards.greenhouse.io","scope_path":"/company-a"}` | 通过 |
| `contract.verification.job_id_matches_direct_path` | contract_boundary | official_domain_guardrail | `true` | `true` | 通过 |
| `contract.verification.article_id_is_not_job_identity` | contract_boundary | official_domain_guardrail | `false` | `false` | 通过 |
| `contract.verification.graduation_year_is_not_job_identity` | contract_boundary | official_domain_guardrail | `false` | `false` | 通过 |
| `contract.verification.campaign_token_is_not_job_identity` | contract_boundary | official_domain_guardrail | `false` | `false` | 通过 |
| `contract.verification.unresolved_page_cannot_write_claims` | contract_boundary | official_domain_guardrail | `{"error":"页面未找到、访问受阻或未知状态不能写入官网字段 claim"}` | `{"error":"页面未找到、访问受阻或未知状态不能写入官网字段 claim"}` | 通过 |
| `contract.verification.open_requires_exact_posting_url` | contract_boundary | official_domain_guardrail | `{"error":"核验页未结构化匹配当前岗位的官方 ID"}` | `{"error":"核验页未结构化匹配当前岗位的官方 ID"}` | 通过 |
| `contract.verification.shared_ats_rejects_other_tenant` | contract_boundary | official_domain_guardrail | `{"error":"核验链接与岗位官网域名或公司租户路径不匹配"}` | `{"error":"核验链接与岗位官网域名或公司租户路径不匹配"}` | 通过 |
| `sample.classification.ai_product_intern` | heuristic_sample | campaign_posting_classification | `POSTING` | `POSTING` | 通过 |
| `sample.classification.graduate_program` | heuristic_sample | campaign_posting_classification | `CAMPAIGN` | `CAMPAIGN` | 通过 |
| `sample.classification.solution_role` | heuristic_sample | campaign_posting_classification | `POSTING` | `POSTING` | 通过 |
| `sample.classification.role_families` | heuristic_sample | campaign_posting_classification | `CAMPAIGN` | `CAMPAIGN` | 通过 |
| `sample.classification.data_analyst_without_id` | heuristic_sample | campaign_posting_classification | `POSTING` | `POSTING` | 通过 |
| `sample.classification.multi_city_campaign` | heuristic_sample | campaign_posting_classification | `CAMPAIGN` | `CAMPAIGN` | 通过 |
| `sample.dedup.near_match_review` | heuristic_sample | duplicate_candidate_decision | `REVIEW` | `REVIEW` | 通过 |
| `sample.dedup.distinct_official_posts` | heuristic_sample | duplicate_candidate_decision | `SEPARATE` | `SEPARATE` | 通过 |

Contract 样本用于防止边界回归，必须 100% 通过。Heuristic sample 的比率不可外推。
输入、期望与来源声明可在 `evaluation/fixtures/gold.json` 逐条审阅。

## 数据库数据质量概况

### 表计数

| 对象 | 数量 |
|---|---:|
| `sources` | 3 |
| `import_batches` | 3 |
| `raw_records` | 7919 |
| `organizations` | 6079 |
| `opportunities` | 7890 |
| `opportunity_origins` | 7909 |
| `field_claims` | 79648 |
| `duplicate_candidates` | 0 |
| `verification_attempts` | 0 |
| `decision_snapshots` | 0 |
| `profile_facts` | 0 |
| `preferences` | 0 |
| `shortlist_entries` | 0 |

### 结构完整性

| 检查 | 结果 |
|---|---:|
| `raw_records_with_origin` | 7909 |
| `raw_records_without_origin` | 10 |
| `raw_materialization_coverage` | 0.998737 |
| `opportunities_with_origin` | 7890 |
| `opportunities_without_origin` | 0 |
| `opportunity_origin_coverage` | 1.0 |
| `active_selected_claim_duplicate_groups` | 0 |
| `current_decision_duplicate_groups` | 0 |
| `verified_official_domains` | 0 |
| `scope_and_domain_applicable_verifications` | 0 |

### 分布

- `raw_parse_status`：`{"PARSED":7910,"PARTIAL":7,"REJECTED":2}`
- `raw_kind_prediction`：`{"CAMPAIGN":4637,"POSTING":3282}`
- `opportunity_kind`：`{"CAMPAIGN":4631,"POSTING":3259}`
- `opportunity_review_status`：`{"PENDING":1839,"REVIEW":6051}`
- `duplicate_decision`：`{}`
- `verification_result`：`{}`
- `current_decision_eligibility`：`{}`
- `current_decision_evidence_fit`：`{}`
- `current_decision_trust`：`{}`

## API 本地性能观测

此数据是同进程 FastAPI TestClient 在指定本地数据库上的观测，不是生产 SLO。

| 端点 | 样本 | HTTP | min ms | median ms | p95 ms | max ms |
|---|---:|---|---:|---:|---:|---:|
| `opportunity_list_first_page` | 5 | [200] | 31.25 | 31.77 | 32.29 | 32.38 |
| `workspace_dashboard` | 5 | [200] | 58.91 | 60.92 | 61.72 | 61.8 |
| `opportunity_detail` | 5 | [200] | 3.69 | 3.82 | 4.28 | 4.33 |

## 局限

- These fixtures are not sampled from applicants, employers, interviews, or production traffic.
- Contract cases test declared safety boundaries; heuristic samples only measure this small developer-authored set.
- No result may be presented as a user-study, hiring-outcome, or real-world accuracy claim.
- API timings are local-process observations, not production SLOs.
- Database quality reports structural completeness, not semantic correctness of every row.
