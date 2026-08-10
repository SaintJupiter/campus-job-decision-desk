import {
  ArrowRight,
  BadgeCheck,
  CalendarClock,
  Database,
  RefreshCw,
  SearchCheck,
  ShieldAlert,
  Target,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useState } from "react";

import {
  api,
  type DashboardSummary,
  type Decision,
  type OpportunityDetail,
  type PaginatedOpportunities,
} from "../api";
import {
  EligibilityBadge,
  EmptyState,
  ErrorBlock,
  FitBadge,
  LoadingBlock,
  OpportunityCard,
  PageHeader,
  SectionHeading,
  TrustBadge,
} from "../components";
import { useRemote } from "../useRemote";
import { useRuntime } from "../runtime";

export function DashboardPage() {
  const runtime = useRuntime();
  const [actionError, setActionError] = useState("");
  const [recomputing, setRecomputing] = useState(false);
  const summary = useRemote(() =>
    api<DashboardSummary>("/api/workspace/dashboard"),
  );
  const ready = useRemote(() =>
    api<PaginatedOpportunities>(
      "/api/workspace/decision-queue?queue=ready&page=1&page_size=4",
    ),
  );
  const verifyFirst = useRemote(() =>
    api<PaginatedOpportunities>(
      "/api/workspace/decision-queue?queue=verify_first&page=1&page_size=4",
    ),
  );
  const focusItem = ready.data?.items[0] ?? verifyFirst.data?.items[0];
  const focusLabel = ready.data?.items[0] ? "今日首选" : "今日推荐";
  const focusDetail = useRemote<OpportunityDetail | null>(
    () =>
      focusItem
        ? api<OpportunityDetail>(`/api/opportunities/${focusItem.id}`)
        : Promise.resolve(null),
    [focusItem?.id],
  );

  async function recompute() {
    if (runtime.read_only) return;
    setRecomputing(true);
    setActionError("");
    try {
      await api("/api/workspace/decisions/recompute", {
        method: "POST",
        body: JSON.stringify({ opportunity_ids: null }),
      });
      summary.reload();
      ready.reload();
      verifyFirst.reload();
      focusDetail.reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "重新计算失败");
    } finally {
      setRecomputing(false);
    }
  }

  return (
    <div className="dashboard-page">
      <PageHeader
        eyebrow="TODAY · EVIDENCE TO ACTION"
        title="今天先确定 5 个可信岗位"
        description="先处理能改变投递决定的证据，不把招聘活动、聚合城市或失效页面当作具体职位。"
        actions={
          runtime.read_only ? undefined : (
            <button
              className="button secondary"
              onClick={recompute}
              disabled={recomputing}
            >
              <RefreshCw size={16} />
              {recomputing ? "正在计算…" : "重新计算三轴"}
            </button>
          )
        }
      />

      {actionError && (
        <div className="notice error" role="alert">
          <ShieldAlert size={18} />
          <span>{actionError}</span>
        </div>
      )}

      {summary.loading ? (
        <LoadingBlock label="正在汇总今日工作区…" />
      ) : summary.error ? (
        <ErrorBlock message={summary.error} onRetry={summary.reload} />
      ) : summary.data ? (
        <>
          <div className="dashboard-decision-hero">
            <div className="dashboard-goal-stack">
              <section className="goal-panel">
                <div className="goal-copy">
                  <div className="goal-icon">
                    <Target size={22} />
                  </div>
                  <div>
                    <span>今日可信投递目标</span>
                    <strong>
                      {summary.data.shortlist_ready_count} /{" "}
                      {summary.data.today_goal}
                    </strong>
                    <p>只统计硬条件通过、官网在招的具体岗位。</p>
                  </div>
                </div>
                <div
                  className="goal-meter"
                  aria-label={`已完成 ${summary.data.shortlist_ready_count} 个，共 ${summary.data.today_goal} 个；短名单共保留 ${summary.data.shortlist_total_count} 个`}
                >
                  <span
                    style={{
                      width: `${Math.min(100, (summary.data.shortlist_ready_count / summary.data.today_goal) * 100)}%`,
                    }}
                  />
                </div>
                <NavLink className="button primary" to="/shortlist">
                  查看短名单 <ArrowRight size={16} />
                </NavLink>
              </section>

              <section className="metric-grid" aria-label="工作区概览">
                <Metric
                  icon={<Database />}
                  label="岗位线索"
                  value={summary.data.opportunity_count}
                  detail={`${summary.data.posting_count} 个具体岗位`}
                  to="/jobs"
                />
                <Metric
                  icon={<BadgeCheck />}
                  label="可直接投"
                  value={summary.data.ready_count}
                  detail="已核验"
                  tone="positive"
                  to="/shortlist"
                />
                <Metric
                  icon={<SearchCheck />}
                  label="优先核验"
                  value={summary.data.verify_first_count}
                  detail="缺关键证据"
                  tone="warning"
                  to="/verify"
                />
                <Metric
                  icon={<CalendarClock />}
                  label="未解冲突"
                  value={summary.data.unresolved_conflict_count}
                  detail="字段级处理"
                  tone="negative"
                  to="/jobs?conflict_only=true"
                />
              </section>
            </div>

            <FocusEvidencePreview
              item={focusItem}
              label={focusLabel}
              detail={focusDetail.data}
              loading={focusDetail.loading}
              error={focusDetail.error}
              onRetry={focusDetail.reload}
            />
          </div>

          {summary.data.independent_source_count < 2 && (
            <div className="notice warning">
              <ShieldAlert size={19} />
              <div>
                <strong>
                  当前只有 {summary.data.independent_source_count} 个独立来源
                </strong>
                <p>
                  暂不能比较供应商质量或“独有有效岗位”贡献；同一供应商的多个快照不算独立来源。
                </p>
              </div>
              <NavLink className="text-link" to="/sources">
                检查数据来源 <ArrowRight size={14} />
              </NavLink>
            </div>
          )}
        </>
      ) : null}

      <div className="dashboard-workspace">
        {ready.data && ready.data.items.length > 1 && (
          <section className="content-section dashboard-primary-list">
            <SectionHeading
              title="其他可直接投"
              description="首选岗位已在上方展开，这里保留其余已核验机会。"
              action={
                <NavLink className="text-link" to="/jobs">
                  查看全部岗位 <ArrowRight size={14} />
                </NavLink>
              }
            />
            <div className="card-grid">
              {ready.data.items.slice(1).map((item) => (
                <OpportunityCard key={item.id} item={item} compact />
              ))}
            </div>
          </section>
        )}

        <section className="content-section dashboard-verify-list">
          <SectionHeading
            title="其他岗位推荐"
            description="与你的目标方向相近，按值得进一步查看的优先级排序；未完成官网核验的岗位会明确标记。"
            action={
              <NavLink className="text-link" to="/jobs">
                查看全部岗位 <ArrowRight size={14} />
              </NavLink>
            }
          />
          {verifyFirst.loading ? (
            <LoadingBlock />
          ) : verifyFirst.error ? (
            <ErrorBlock
              message={verifyFirst.error}
              onRetry={verifyFirst.reload}
            />
          ) : verifyFirst.data?.items.length ? (
            <div className="card-grid">
              {verifyFirst.data.items
                .filter((item) => item.id !== focusItem?.id)
                .map((item) => (
                  <OpportunityCard key={item.id} item={item} compact />
                ))}
            </div>
          ) : (
            <EmptyState
              title="没有待优先核验的岗位线索"
              description="新出现的冲突和未知项会在这里排队。"
            />
          )}
        </section>
      </div>
    </div>
  );
}

function FocusEvidencePreview({
  item,
  label,
  detail,
  loading,
  error,
  onRetry,
}: {
  item?: PaginatedOpportunities["items"][number];
  label: string;
  detail: OpportunityDetail | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  if (!item) {
    return (
      <section className="focus-evidence-panel">
        <EmptyState
          title="还没有首选岗位"
          description="导入岗位并完成一次三轴决策后，证据链会直接出现在首页。"
        />
      </section>
    );
  }
  if (loading)
    return (
      <section className="focus-evidence-panel">
        <LoadingBlock label="正在装配首选岗位证据链…" />
      </section>
    );
  if (error)
    return (
      <section className="focus-evidence-panel">
        <ErrorBlock message={error} onRetry={onRetry} />
      </section>
    );

  const currentDecision = detail?.item.decision_current
    ? detail.decision_history.find((decision) => decision.is_current)
    : undefined;
  const verification = detail?.verifications[0];
  const evidenceLinks = currentDecision
    ? Array.from(
        new Map(
          currentDecision.evidence_links.map((evidence) => [
            evidence.evidence_text.trim(),
            evidence,
          ]),
        ).values(),
      )
    : [];
  const fitReasons =
    currentDecision?.reasons
      .filter((reason) => reason.axis === "evidence_fit")
      .map((reason) => reason.message) ?? [];
  const firstUnknown = currentDecision?.unknowns[0]?.message;
  const roleDirection = roleDirectionLabel(item.title);
  const capabilityLabels = fitReasons.map((reason) =>
    reason.includes("：") ? reason.split("：").at(-1)! : reason,
  );
  const primaryEvidence = evidenceLinks[0]?.evidence_text ?? "";
  const secondaryEvidence = evidenceLinks[1]?.evidence_text ?? "";
  const officialTask = extractOfficialTask(
    verification?.evidence_excerpt ?? "",
  );
  const hardConditionSummary = [
    item.cities.includes("上海")
      ? "上海可选"
      : item.cities.length === 1
        ? item.cities[0]
        : "城市待筛选",
    item.graduation_years.includes("2027届")
      ? "2027届"
      : item.graduation_years[0],
  ]
    .filter(Boolean)
    .join("、");
  return (
    <section className="focus-evidence-panel" aria-label="今日首选岗位证据链">
      <header className="focus-evidence-head">
        <div>
          <span>{label} · EVIDENCE CHAIN</span>
          <h2>{item.title || "未命名岗位"}</h2>
          <p>{item.company || "公司待确认"}</p>
          {item.title_inferred && (
            <small className="focus-inference-note">
              根据招聘项目表述推断 · 具体名称待官网确认
            </small>
          )}
          <div className="focus-job-meta" aria-label="首选岗位关键信息">
            {item.cities.slice(0, 2).map((city) => (
              <span key={city}>{city}</span>
            ))}
            {item.graduation_years.slice(0, 1).map((year) => (
              <span key={year}>{year}</span>
            ))}
            <span>{item.source_count} 个独立来源</span>
          </div>
        </div>
        <div className="focus-primary-actions">
          <NavLink className="button primary small" to={`/jobs/${item.id}`}>
            {item.kind === "CAMPAIGN" ? "查找具体岗位" : "查看并投递"}
            <ArrowRight size={18} />
          </NavLink>
          <NavLink className="button secondary small" to={`/jobs/${item.id}`}>
            完整证据
          </NavLink>
        </div>
      </header>

      {currentDecision ? (
        <>
          <div className="focus-section-label">
            <strong>三轴结论</strong>
            <span>能不能投 · 适不适合 · 信息可不可信</span>
          </div>
          <div className="focus-axis-grid">
            <FocusAxis
              label="可投性"
              badge={<EligibilityBadge value={currentDecision.eligibility} />}
              reason={
                hardConditionSummary
                  ? `${hardConditionSummary}；${
                      verification
                        ? "开放状态已有官网证据"
                        : "开放状态仍需官网核验"
                    }`
                  : axisReason(currentDecision, "eligibility")
              }
            />
            <FocusAxis
              label="经历证据"
              badge={<FitBadge value={currentDecision.evidence_fit} />}
              reason={
                primaryEvidence
                  ? `${capabilityLabels.join(" / ")} 有经历支撑；${conciseEvidence(primaryEvidence, 30)}`
                  : axisReason(currentDecision, "evidence_fit")
              }
            />
            <FocusAxis
              label="信息可信度"
              badge={<TrustBadge value={currentDecision.trust} />}
              reason={`${verification ? "官方具体岗位页已核验" : axisReason(currentDecision, "trust")}${item.conflict_count ? `；${item.conflict_count} 项冲突已保留` : ""}`}
            />
          </div>
        </>
      ) : (
        <div className="focus-no-decision">三轴决策待重新计算</div>
      )}

      <div className="match-rationale-head">
        <strong>为什么值得投</strong>
        <span>不给魔法总分，只展示能被追问的理由</span>
      </div>
      <div className="match-rationale-grid">
        <MatchRationale
          index="01"
          label="核心经历"
          value={
            (primaryEvidence && conciseEvidence(primaryEvidence, 64)) ||
            "尚未提取到可追溯的经历能力"
          }
          tone="violet"
        />
        <MatchRationale
          index="02"
          label="任务吻合"
          value={
            primaryEvidence && officialTask
              ? `${conciseEvidence(primaryEvidence, 32)} ↔ ${conciseEvidence(officialTask, 32)}`
              : secondaryEvidence
                ? conciseEvidence(secondaryEvidence, 72)
                : fitReasons.length
                  ? fitReasons.join("；")
                  : `岗位属于${roleDirection}，当前 JD 能力要求仍需补充`
          }
          tone="mint"
        />
        <MatchRationale
          index="03"
          label="需要补强"
          value={
            firstUnknown ||
            "当前证据主要支持方案、需求与数据能力；上线结果和真实用户指标仍需在投递材料中补强"
          }
          tone="coral"
        />
      </div>
    </section>
  );
}

function MatchRationale({
  index,
  label,
  value,
  tone,
}: {
  index: string;
  label: string;
  value: string;
  tone: "violet" | "mint" | "cyan" | "coral";
}) {
  return (
    <article className={`match-rationale-card rationale-${tone}`}>
      <div>
        <span>{index}</span>
        <strong>{label}</strong>
      </div>
      <p>{value}</p>
    </article>
  );
}

function roleDirectionLabel(title: string) {
  if (/(AI|大模型|智能|算法|Agent)/i.test(title)) return "AI 产品";
  if (/(数据|指标|分析)/.test(title)) return "数据产品";
  if (/(技术|平台|工业软件)/.test(title)) return "技术产品";
  if (/(解决方案|交付|咨询)/.test(title)) return "解决方案";
  return "相邻产品方向";
}

function conciseEvidence(text: string, maxLength: number) {
  const cleaned = text
    .replace(/^(项目经历|数据项目|技术经历|经历边界)：/, "")
    .replace(/。+$/, "")
    .trim();
  return cleaned.length > maxLength
    ? `${cleaned.slice(0, maxLength).trim()}…`
    : cleaned;
}

function extractOfficialTask(excerpt: string) {
  if (!excerpt) return "";
  const task = excerpt
    .replace(/^官网具体岗位页显示：/, "")
    .split(/[；。]/)
    .find((part) => /(负责|需求|设计|迭代|分析|建设)/.test(part));
  return task?.trim() ?? "";
}

function FocusAxis({
  label,
  badge,
  reason,
}: {
  label: string;
  badge: React.ReactNode;
  reason: string;
}) {
  return (
    <article className="focus-axis-card">
      <div>
        <span>{label}</span>
        {badge}
      </div>
      <p>{reason}</p>
    </article>
  );
}

function axisReason(
  decision: Decision,
  axis: "eligibility" | "evidence_fit" | "trust",
) {
  return (
    decision.reasons.find((reason) => reason.axis === axis)?.message ??
    decision.unknowns.find((reason) => reason.axis === axis)?.message ??
    "当前没有更多解释。"
  );
}

function Metric({
  icon,
  label,
  value,
  detail,
  tone = "neutral",
  to,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  detail: string;
  tone?: "neutral" | "positive" | "warning" | "negative";
  to: string;
}) {
  return (
    <NavLink className={`metric-card metric-${tone}`} to={to}>
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value.toLocaleString("zh-CN")}</strong>
      <p>{detail}</p>
      <ArrowRight className="metric-arrow" size={15} aria-hidden="true" />
    </NavLink>
  );
}
