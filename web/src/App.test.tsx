import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { Opportunity } from "./api";
import { OpportunityCard } from "./components";

const dashboard = {
  opportunity_count: 0,
  posting_count: 0,
  campaign_count: 0,
  shortlist_total_count: 0,
  shortlist_ready_count: 0,
  ready_count: 0,
  verify_first_count: 0,
  unresolved_conflict_count: 0,
  latest_import_at: null,
  independent_source_count: 0,
  today_goal: 5,
};

const evaluation = {
  schema_version: "test",
  harness_version: "evaluation-harness.v1",
  generated_at: "2026-08-10T00:00:00Z",
  methodology: {
    contract_definition: "contract",
    database_policy: "aggregate only",
    fixture_data_class: "fully synthetic",
    heuristic_sample_definition: "synthetic regression",
    outcome_claim_policy: "no hiring claims",
  },
  fixture_summary: {
    contract_boundary: {
      exact_match_rate_on_fixture_set: 1,
      failed: 0,
      passed: 25,
      total: 25,
    },
    heuristic_sample: {
      exact_match_rate_on_fixture_set: 1,
      failed: 0,
      passed: 8,
      total: 8,
    },
  },
  database_quality: {
    database_label: "private-baseline",
    privacy_mode: "aggregate_only",
    distributions: {
      raw_parse_status: { PARSED: 7910, PARTIAL: 7, REJECTED: 2 },
      opportunity_kind: { CAMPAIGN: 4631, POSTING: 3259 },
    },
    structural_checks: {
      active_selected_claim_duplicate_groups: 0,
      current_decision_duplicate_groups: 0,
      opportunities_with_origin: 7890,
      opportunities_without_origin: 0,
      opportunity_origin_coverage: 1,
      raw_materialization_coverage: 0.998737,
      raw_records_with_origin: 7909,
      raw_records_without_origin: 10,
    },
    table_counts: {
      raw_records: 7919,
      opportunities: 7890,
      field_claims: 79648,
      sources: 3,
    },
  },
  api_performance: {
    measurement_scope: "local test",
    is_production_slo: false,
    endpoints: [
      {
        endpoint: "opportunity_detail",
        http_statuses: [200],
        latency_ms: { min: 3.25, median: 3.35, p95: 3.6, max: 3.65 },
        sample_count: 5,
        status: "measured",
      },
    ],
  },
  limitations: ["synthetic fixtures"],
};

function response(payload: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(payload),
  } as Response);
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/meta"))
        return response({
          environment: "test",
          read_only: false,
          data_mode: "local-workspace",
          label: "测试工作区",
        });
      if (url.includes("/api/workspace/dashboard")) return response(dashboard);
      if (url.includes("/api/evaluation/summary")) return response(evaluation);
      if (url.includes("/api/sources/preview"))
        return response({
          file_name: "jobs.csv",
          file_format: "csv",
          file_hash: "abcdef1234567890",
          header: ["公司", "岗位"],
          mapping: { company: "公司", title: "岗位" },
          mapping_version: "canonical-v1",
          row_count: 2,
          success_count: 2,
          error_count: 0,
          kind_counts: { CAMPAIGN: 1, POSTING: 1, NON_JOB: 0 },
          sample_rows: [
            {
              row_number: 1,
              canonical: {
                company: "示例公司",
                title: "AI 产品实习生",
                cities: ["上海"],
              },
              kind: {
                kind: "POSTING",
                confidence: 0.9,
                reasons: ["包含具体岗位名称"],
                needs_review: false,
              },
              parse_status: "PARSED",
              errors: [],
            },
          ],
          rejected_rows: [],
        });
      if (url.includes("/api/sources/connectors/feishu/preview"))
        return response({
          app_token: "base-token",
          table_id: "tblHeojHV94NEKZF",
          view_id: "vewNoiv4Wg",
          page_count: 3,
          field_count: 12,
          fetched_at: "2026-08-10T00:00:00Z",
          preview: {
            file_name: "feishu-2026-08-10.csv",
            file_format: "feishu-bitable",
            file_hash: "fedcba1234567890",
            header: ["记录ID", "公司名称", "招聘岗位"],
            mapping: { company: "公司名称", title: "招聘岗位" },
            mapping_version: "canonical-v1",
            row_count: 7980,
            success_count: 7980,
            error_count: 0,
            kind_counts: { CAMPAIGN: 4000, POSTING: 3980, NON_JOB: 0 },
            sample_rows: [],
            rejected_rows: [],
          },
        });
      if (url.includes("/api/sources/connectors")) return response([]);
      if (url.includes("/api/sources/sync-runs")) return response([]);
      if (url.includes("/api/sources/batches")) return response([]);
      if (url.endsWith("/api/sources")) return response([]);
      if (url.includes("/api/opportunities") || url.includes("/decision-queue"))
        return response({ items: [], total: 0, page: 1, page_size: 100 });
      if (url.includes("/api/workspace/profile"))
        return response({ facts: [], preferences: [] });
      return response({});
    }),
  );
});

afterEach(() => cleanup());

describe("App", () => {
  it("renders the evidence-first workspace and today goal", async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText("校招岗位决策台")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "今天先确定 5 个可信岗位" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("0 / 5")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "岗位工作区" }),
    ).toBeInTheDocument();
  });

  it("explains the portfolio product before asking visitors to use it", () => {
    render(
      <MemoryRouter initialEntries={["/about"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: /多份校招表.*先核验，再决定/u }),
    ).toBeInTheDocument();
    expect(screen.getByText("区分招聘项目与具体岗位")).toBeInTheDocument();
    expect(screen.getByText(/可追溯的投递判断/u)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "开始规划投递" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });

  it("opens the profile drawer with facts and preferences separated", async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    await screen.findByText("测试工作区");
    fireEvent.click(screen.getByRole("button", { name: "打开我的证据画像" }));
    expect(
      screen.getByRole("dialog", { name: "我的证据画像" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "1. 提供简历证据" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "上传并提取候选事实" }),
    ).toBeDisabled();
    const resumeInput = document.querySelector<HTMLInputElement>(
      'input[type="file"][accept*=".pdf"]',
    );
    expect(resumeInput).not.toBeNull();
    expect((resumeInput as HTMLInputElement).tabIndex).toBe(0);
    (resumeInput as HTMLInputElement).focus();
    expect(resumeInput).toHaveFocus();
    expect(
      screen.getByRole("heading", { name: "3. 确认求职偏好" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/workspace/profile",
        expect.anything(),
      ),
    );
  });

  it("requires a successful source preview before import", async () => {
    render(
      <MemoryRouter initialEntries={["/sources"]}>
        <App />
      </MemoryRouter>,
    );

    await screen.findByText("测试工作区");
    expect(
      screen.getByRole("button", { name: "确认导入并生成批次" }),
    ).toBeDisabled();
    const fileInput = document.querySelector<HTMLInputElement>(
      'input[type="file"][accept*=".csv"]',
    );
    expect(fileInput).not.toBeNull();
    expect((fileInput as HTMLInputElement).tabIndex).toBe(0);
    (fileInput as HTMLInputElement).focus();
    expect(fileInput).toHaveFocus();
    fireEvent.change(fileInput as HTMLInputElement, {
      target: {
        files: [new File(["公司,岗位"], "jobs.csv", { type: "text/csv" })],
      },
    });
    fireEvent.change(
      screen.getAllByRole("textbox", { name: "来源名称" }).at(0) as HTMLElement,
      { target: { value: "测试供应商" } },
    );
    fireEvent.change(
      screen
        .getAllByRole("textbox", { name: "独立来源组" })
        .at(0) as HTMLElement,
      {
        target: { value: "vendor-test" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "先预览解析" }));

    expect(
      await screen.findByText("预览完成，可以确认导入"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "确认导入并生成批次" }),
    ).toBeEnabled();
    expect(screen.getByText("AI 产品实习生")).toBeInTheDocument();
  });

  it("offers a full-page Feishu source preview before saving a connector", async () => {
    render(
      <MemoryRouter initialEntries={["/sources"]}>
        <App />
      </MemoryRouter>,
    );

    await screen.findByText("连接飞书多维表格");
    fireEvent.change(
      screen.getByRole("textbox", { name: "飞书多维表格 URL" }),
      {
        target: {
          value:
            "https://vendor.feishu.cn/base/token?table=tblHeojHV94NEKZF&view=vewNoiv4Wg",
        },
      },
    );
    const sourceNameInputs = screen.getAllByRole("textbox", {
      name: "来源名称",
    });
    fireEvent.change(sourceNameInputs.at(1) as HTMLElement, {
      target: { value: "飞书每日表" },
    });
    fireEvent.click(screen.getByRole("button", { name: "检测并全量预览" }));

    expect(
      await screen.findByText(/3 页、7980 行、12 个字段/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "保存连接并生成首个快照" }),
    ).toBeEnabled();
  });

  it("exposes decision filters in the job pool and sends them to the API", async () => {
    render(
      <MemoryRouter initialEntries={["/jobs"]}>
        <App />
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "岗位池" });
    fireEvent.change(screen.getByLabelText("城市"), {
      target: { value: "上海" },
    });
    fireEvent.change(screen.getByLabelText("届次"), {
      target: { value: "2027" },
    });
    fireEvent.change(screen.getByLabelText("硬条件判断"), {
      target: { value: "PASS" },
    });
    fireEvent.change(screen.getByLabelText("可信度"), {
      target: { value: "VERIFIED" },
    });
    fireEvent.click(screen.getByLabelText("只看冲突"));

    await waitFor(() => {
      const matchingRequest = vi.mocked(fetch).mock.calls.find(([input]) => {
        const url = new URL(String(input), "http://localhost");
        return (
          url.pathname === "/api/opportunities" &&
          url.searchParams.get("city") === "上海" &&
          url.searchParams.get("graduation_year") === "2027" &&
          url.searchParams.get("eligibility") === "PASS" &&
          url.searchParams.get("trust") === "VERIFIED" &&
          url.searchParams.get("conflict_only") === "true"
        );
      });
      expect(matchingRequest).toBeTruthy();
    });
  });

  it("shows evaluation evidence without presenting synthetic fixtures as outcomes", async () => {
    render(
      <MemoryRouter initialEntries={["/evidence"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "效果证据，不是效果口号" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("25/25")).toBeInTheDocument();
    expect(screen.getByText("8/8")).toBeInTheDocument();
    expect(screen.getByText(/不等于提高面试或录用概率/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "打开完整评测报告" }),
    ).toHaveAttribute("href", "/api/evaluation/report");
  });
});

describe("OpportunityCard", () => {
  it("keeps Campaign out of the application flow", () => {
    const campaign: Opportunity = {
      id: "campaign-1",
      kind: "CAMPAIGN",
      company: "星海智能",
      title: "2027 校园招聘",
      official_job_id: null,
      candidate_domain: "",
      official_domain: "",
      official_scope_path: "",
      official_domain_verified: false,
      review_status: "REVIEW",
      cities: ["上海", "杭州", "南京", "苏州", "深圳", "北京"],
      graduation_years: ["2027届"],
      recruitment_type: "秋招",
      employer_type: "国企",
      written_test: "免笔试",
      deadline: "",
      apply_url: "https://example.com/campus",
      source_count: 2,
      conflict_count: 0,
      verification: null,
      eligibility: "UNKNOWN",
      evidence_fit: "UNKNOWN",
      trust: "UNKNOWN",
      decision_current: false,
      needs_recompute: false,
      manual_decision: "UNDECIDED",
      unknowns: [],
      updated_at: "2026-08-10T00:00:00Z",
    };

    render(
      <MemoryRouter>
        <OpportunityCard item={campaign} />
      </MemoryRouter>,
    );

    expect(screen.getByText("招聘项目线索")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "查找具体岗位" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("打开官网")).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getByText("国企")).toBeInTheDocument();
    expect(screen.getByText("免笔试")).toBeInTheDocument();
    expect(screen.getByText("上海、杭州、南京、苏州、深圳…")).toHaveAttribute(
      "title",
      "上海、杭州、南京、苏州、深圳、北京",
    );
  });
});
