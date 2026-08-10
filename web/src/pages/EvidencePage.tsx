import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  Gauge,
  ShieldCheck,
} from "lucide-react";

import { api, type EvaluationSummary, humanDate } from "../api";
import {
  ErrorBlock,
  LoadingBlock,
  PageHeader,
  SectionHeading,
} from "../components";
import { useRemote } from "../useRemote";

const endpointNames: Record<string, string> = {
  opportunity_list_first_page: "岗位池首屏",
  workspace_dashboard: "今日决策汇总",
  opportunity_detail: "岗位证据详情",
};

export function EvidencePage() {
  const result = useRemote(() =>
    api<EvaluationSummary>("/api/evaluation/summary"),
  );

  return (
    <>
      <PageHeader
        eyebrow="EVALUATION · CLAIMS WITH BOUNDARIES"
        title="效果证据，不是效果口号"
        description="这里公开系统能证明什么、用什么样本证明，以及当前仍不能证明什么。"
        actions={
          <a
            className="button secondary"
            href="/api/evaluation/report"
            target="_blank"
            rel="noreferrer"
          >
            打开完整评测报告 <ExternalLink size={15} />
          </a>
        }
      />

      {result.loading ? (
        <LoadingBlock label="正在读取可复现评测…" />
      ) : result.error ? (
        <ErrorBlock message={result.error} onRetry={result.reload} />
      ) : result.data ? (
        <EvidenceContent data={result.data} />
      ) : null}
    </>
  );
}

function EvidenceContent({ data }: { data: EvaluationSummary }) {
  const contract = data.fixture_summary.contract_boundary;
  const heuristic = data.fixture_summary.heuristic_sample;
  const quality = data.database_quality;
  const parsed = quality.distributions.raw_parse_status.PARSED ?? 0;

  return (
    <>
      <div className="notice info evidence-boundary" role="note">
        <AlertTriangle size={19} />
        <div>
          <strong>先读边界：通过回归测试，不等于提高面试或录用概率</strong>
          <p>
            Gold fixtures
            全部是开发者编写的合成样本；私有数据只做结构完整性检查。
            当前没有真实用户对照实验，也没有推荐准确率或招聘结果因果证据。
          </p>
        </div>
      </div>

      <section className="evidence-hero-grid" aria-label="评测摘要">
        <EvidenceMetric
          icon={<ShieldCheck />}
          label="安全边界用例"
          value={`${contract.passed}/${contract.total}`}
          detail="必须全部通过的契约测试"
          tone="positive"
        />
        <EvidenceMetric
          icon={<CheckCircle2 />}
          label="合成启发式样本"
          value={`${heuristic.passed}/${heuristic.total}`}
          detail="小型回归集，不可外推"
          tone="positive"
        />
        <EvidenceMetric
          icon={<Database />}
          label="私有基线原始记录"
          value={quality.table_counts.raw_records.toLocaleString("zh-CN")}
          detail={`${parsed.toLocaleString("zh-CN")} 条完整解析`}
        />
        <EvidenceMetric
          icon={<Gauge />}
          label="原始记录物化覆盖"
          value={formatPercent(
            quality.structural_checks.raw_materialization_coverage,
          )}
          detail="只衡量结构链接，不衡量语义正确"
        />
      </section>

      <section className="content-section">
        <SectionHeading
          title="系统边界是否可复现"
          description={`评测器 ${data.harness_version} · ${humanDate(data.generated_at, true)} 更新`}
        />
        <div className="evidence-check-grid">
          <EvidenceCheck
            title="招聘项目不冒充具体岗位"
            text="招聘项目线索不能直接进入可投排序，具体岗位必须绑定独立身份与页面证据。"
          />
          <EvidenceCheck
            title="页面失败不等于岗位关闭"
            text="NOT_FOUND、BLOCKED 与 UNKNOWN 分开保留，不会自动写成 CLOSED。"
          />
          <EvidenceCheck
            title="官网身份与租户隔离"
            text="域名、共享 ATS 租户路径和官方岗位 ID 必须同时满足约束。"
          />
          <EvidenceCheck
            title="简历事实必须有原文证据"
            text="未确认的抽取候选不会增加 Evidence Fit，也不会替用户补写不存在的经历。"
          />
        </div>
        <p className="evidence-caption">
          上述结论来自 {contract.total}{" "}
          条合成契约用例；它证明代码遵守已声明边界，
          不证明所有真实招聘网站都能被正确解析。
        </p>
      </section>

      <section className="content-section">
        <SectionHeading
          title="私有数据结构质量"
          description="仅输出聚合统计；不输出岗位、公司、来源链接、简历或付费表原文。"
        />
        <div className="evidence-facts">
          <EvidenceFact
            label="机会实体"
            value={quality.table_counts.opportunities}
          />
          <EvidenceFact
            label="字段证据 Claim"
            value={quality.table_counts.field_claims}
          />
          <EvidenceFact
            label="机会来源覆盖"
            value={formatPercent(
              quality.structural_checks.opportunity_origin_coverage,
            )}
          />
          <EvidenceFact
            label="重复当前 Claim 组"
            value={
              quality.structural_checks.active_selected_claim_duplicate_groups
            }
          />
        </div>
        <p className="evidence-caption">
          仍有 {quality.structural_checks.raw_records_without_origin}{" "}
          条原始记录未物化：
          它们包含部分解析或拒绝记录，保留在原始层用于追溯，不会伪造成岗位。
        </p>
      </section>

      <section className="content-section">
        <SectionHeading
          title="本地接口性能观测"
          description="FastAPI TestClient 同进程测量，每个端点 5 次；不是线上 SLO。"
        />
        <div className="table-wrap">
          <table className="evidence-table">
            <thead>
              <tr>
                <th>用户动作</th>
                <th>HTTP</th>
                <th>中位延迟</th>
                <th>P95</th>
                <th>样本</th>
              </tr>
            </thead>
            <tbody>
              {data.api_performance.endpoints.map((endpoint) => (
                <tr key={endpoint.endpoint}>
                  <td>
                    {endpointNames[endpoint.endpoint] ?? endpoint.endpoint}
                  </td>
                  <td>{endpoint.http_statuses.join("/")}</td>
                  <td>{endpoint.latency_ms.median.toFixed(2)} ms</td>
                  <td>{endpoint.latency_ms.p95.toFixed(2)} ms</td>
                  <td>{endpoint.sample_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="content-section evidence-next">
        <SectionHeading
          title="下一步验证"
          description="把工程正确性继续推进到真实使用价值。"
        />
        <ol>
          <li>邀请至少 3 名同学完成同一项 15 分钟选岗任务。</li>
          <li>比较原表手筛与系统的 time-to-5、误资格数和官网确认数。</li>
          <li>记录人工纠错与 Bad Case，完成一次有证据的产品迭代。</li>
        </ol>
      </section>
    </>
  );
}

function EvidenceMetric({
  icon,
  label,
  value,
  detail,
  tone = "neutral",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "positive";
}) {
  return (
    <article className={`evidence-metric evidence-${tone}`}>
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function EvidenceCheck({ title, text }: { title: string; text: string }) {
  return (
    <article className="evidence-check">
      <CheckCircle2 size={18} />
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
      </div>
    </article>
  );
}

function EvidenceFact({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="evidence-fact">
      <span>{label}</span>
      <strong>
        {typeof value === "number" ? value.toLocaleString("zh-CN") : value}
      </strong>
    </div>
  );
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(value >= 0.9995 ? 1 : 2)}%`;
}
