import { beforeAll, describe, expect, it, vi } from "vitest";

import { staticDemoApi } from "./staticDemo";

const opportunity = {
  id: "posting-1",
  kind: "POSTING",
  company: "合成科技",
  title: "机器人产品经理",
  source_title: "机器人产品经理",
  title_inferred: false,
  official_job_id: "JOB-1",
  candidate_domain: "careers.example",
  official_domain: "careers.example",
  official_scope_path: "/jobs",
  official_domain_verified: true,
  review_status: "ACTIVE",
  cities: ["上海"],
  graduation_years: ["2027届"],
  recruitment_type: "秋招",
  employer_type: "民营企业",
  written_test: "有笔试",
  deadline: "2026-08-20",
  apply_url: "https://careers.example/jobs/JOB-1",
  source_count: 2,
  conflict_count: 0,
  verification: "OPEN",
  eligibility: "PASS",
  evidence_fit: "PRIMARY",
  trust: "VERIFIED",
  decision_current: true,
  needs_recompute: false,
  manual_decision: "PREPARE_APPLY",
  unknowns: [],
  updated_at: "2026-08-11T00:00:00Z",
};

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        schema_version: "static-demo.v1",
        generated_at: "2026-08-11T00:00:00Z",
        meta: {
          environment: "static-demo",
          read_only: true,
          data_mode: "synthetic-demo",
          label: "在线合成演示",
        },
        dashboard: {},
        opportunities: [opportunity],
        ready_queue: [opportunity],
        verify_first_queue: [],
        details: {},
        profile: { facts: [], preferences: [] },
        shortlist: [],
        sources: [],
        batches: [],
        connectors: [],
        sync_runs: [],
        duplicates: [],
        evaluation: {},
      }),
    }),
  );
});

describe("staticDemoApi", () => {
  it("serves static runtime metadata", async () => {
    await expect(staticDemoApi("/api/meta")).resolves.toMatchObject({
      environment: "static-demo",
      read_only: true,
    });
  });

  it("filters and paginates embedded opportunities", async () => {
    await expect(
      staticDemoApi(
        "/api/opportunities?search=机器人&city=上海&graduation_year=2027&page=1&page_size=20",
      ),
    ).resolves.toMatchObject({ total: 1, items: [{ id: "posting-1" }] });
  });

  it("keeps the online demo read-only", async () => {
    await expect(
      staticDemoApi("/api/workspace/profile", { method: "POST" }),
    ).rejects.toThrow("只读合成数据");
  });
});
