import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Download,
  ExternalLink,
  FileJson,
  FileText,
  ListChecks,
  Trash2,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useState } from "react";

import {
  api,
  humanDate,
  isConfirmedOfficialLink,
  type ApplicationStage,
  type ShortlistEntry,
} from "../api";
import {
  AxisStrip,
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  PageHeader,
} from "../components";
import { useRuntime } from "../runtime";
import { useRemote } from "../useRemote";

export function ShortlistPage() {
  const runtime = useRuntime();
  const [removing, setRemoving] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [savingProgress, setSavingProgress] = useState<string | null>(null);
  const [progressDrafts, setProgressDrafts] = useState<
    Record<
      string,
      {
        stage: ApplicationStage;
        next_action: string;
        next_action_at: string;
      }
    >
  >({});
  const shortlist = useRemote(() =>
    api<ShortlistEntry[]>("/api/workspace/shortlist"),
  );

  async function remove(id: string) {
    if (runtime.read_only) return;
    setRemoving(id);
    setActionError("");
    try {
      await api(`/api/workspace/shortlist/${id}`, { method: "DELETE" });
      shortlist.reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "移除失败");
    } finally {
      setRemoving(null);
    }
  }

  async function saveProgress(entry: ShortlistEntry) {
    if (runtime.read_only) return;
    const draft = progressDrafts[entry.opportunity.id] ?? {
      stage: entry.application_stage,
      next_action: entry.next_action,
      next_action_at: toDateInput(entry.next_action_at),
    };
    setSavingProgress(entry.opportunity.id);
    setActionError("");
    try {
      await api(
        `/api/workspace/shortlist/${entry.opportunity.id}/application`,
        {
          method: "PATCH",
          body: JSON.stringify({
            stage: draft.stage,
            next_action: draft.next_action,
            next_action_at: draft.next_action_at
              ? `${draft.next_action_at}T09:00:00+08:00`
              : null,
          }),
        },
      );
      shortlist.reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "进度保存失败");
    } finally {
      setSavingProgress(null);
    }
  }

  const stageCounts = Object.fromEntries(
    APPLICATION_STAGES.map(({ value }) => [
      value,
      shortlist.data?.filter((item) => item.application_stage === value)
        .length ?? 0,
    ]),
  ) as Record<ApplicationStage, number>;

  return (
    <>
      <PageHeader
        eyebrow="TRUSTED APPLY QUEUE"
        title="可信投递计划"
        description="先用证据确认能投，再跟踪待投递、笔试、面试与 Offer；岗位状态变化仍会阻断错误投递。"
        actions={
          <div className="export-actions">
            <a
              className="button secondary"
              href="/api/workspace/shortlist/export?format=csv"
            >
              <Download size={15} />
              CSV
            </a>
            <a
              className="button secondary"
              href="/api/workspace/shortlist/export?format=json"
            >
              <FileJson size={15} />
              JSON
            </a>
            <a
              className="button secondary"
              href="/api/workspace/shortlist/export?format=markdown"
            >
              <FileText size={15} />
              Markdown
            </a>
          </div>
        }
      />
      <section className="application-stage-summary" aria-label="投递进度概览">
        {APPLICATION_STAGES.slice(0, 5).map((stage) => (
          <div key={stage.value}>
            <span>{stage.label}</span>
            <strong>{stageCounts[stage.value] ?? 0}</strong>
          </div>
        ))}
      </section>
      <div className="notice info">
        <CheckCircle2 size={18} />
        <div>
          <strong>导出只包含当前可投的记录</strong>
          <p>
            旧短名单若因画像变化、核验过期或人工暂缓而失效，会继续显示在页面中，但不会进入导出文件。
          </p>
        </div>
      </div>
      {actionError && (
        <div className="notice error" role="alert">
          <AlertTriangle size={18} />
          <span>{actionError}</span>
        </div>
      )}

      {shortlist.loading ? (
        <LoadingBlock />
      ) : shortlist.error ? (
        <ErrorBlock message={shortlist.error} onRetry={shortlist.reload} />
      ) : shortlist.data?.length ? (
        <div className="shortlist-list">
          {shortlist.data.map((entry, index) => (
            <article
              key={entry.opportunity.id}
              className={`shortlist-card ${entry.ready ? "is-ready" : "is-blocked"}`}
            >
              <div className="shortlist-rank">
                {String(index + 1).padStart(2, "0")}
              </div>
              <div className="shortlist-main">
                <div className="shortlist-title">
                  <div>
                    <span>{entry.opportunity.company}</span>
                    <h2>{entry.opportunity.title}</h2>
                  </div>
                  <div className="shortlist-state">
                    <strong>优先级 {entry.priority}</strong>
                    <span
                      className={entry.ready ? "ready-chip" : "blocked-chip"}
                    >
                      {entry.ready ? (
                        <CheckCircle2 size={12} />
                      ) : (
                        <AlertTriangle size={12} />
                      )}
                      {entry.ready ? "可导出投递" : "当前被阻断"}
                    </span>
                  </div>
                </div>
                <div className="metadata-row">
                  <span>
                    {entry.opportunity.cities.join("、") || "城市待确认"}
                  </span>
                  <span>
                    {entry.opportunity.graduation_years.join("、") ||
                      "届次待确认"}
                  </span>
                  <span>加入于 {humanDate(entry.added_at, true)}</span>
                </div>
                <AxisStrip item={entry.opportunity} />
                <div className="application-progress-panel">
                  <div className="application-progress-heading">
                    <div>
                      <CalendarClock size={17} />
                      <strong>投递进度与下一步</strong>
                    </div>
                    {entry.applied_at && (
                      <span>投递于 {humanDate(entry.applied_at, true)}</span>
                    )}
                  </div>
                  <div className="application-progress-fields">
                    <label>
                      <span>当前阶段</span>
                      <select
                        disabled={runtime.read_only}
                        value={
                          progressDrafts[entry.opportunity.id]?.stage ??
                          entry.application_stage
                        }
                        onChange={(event) =>
                          setProgressDrafts((current) => ({
                            ...current,
                            [entry.opportunity.id]: {
                              stage: event.target.value as ApplicationStage,
                              next_action:
                                current[entry.opportunity.id]?.next_action ??
                                entry.next_action,
                              next_action_at:
                                current[entry.opportunity.id]?.next_action_at ??
                                toDateInput(entry.next_action_at),
                            },
                          }))
                        }
                      >
                        {APPLICATION_STAGES.map((stage) => (
                          <option key={stage.value} value={stage.value}>
                            {stage.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="application-next-action">
                      <span>下一步行动</span>
                      <input
                        disabled={runtime.read_only}
                        value={
                          progressDrafts[entry.opportunity.id]?.next_action ??
                          entry.next_action
                        }
                        placeholder="例如：今晚完成网申并记录简历版本"
                        onChange={(event) =>
                          setProgressDrafts((current) => ({
                            ...current,
                            [entry.opportunity.id]: {
                              stage:
                                current[entry.opportunity.id]?.stage ??
                                entry.application_stage,
                              next_action: event.target.value,
                              next_action_at:
                                current[entry.opportunity.id]?.next_action_at ??
                                toDateInput(entry.next_action_at),
                            },
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>计划日期</span>
                      <input
                        type="date"
                        disabled={runtime.read_only}
                        value={
                          progressDrafts[entry.opportunity.id]
                            ?.next_action_at ??
                          toDateInput(entry.next_action_at)
                        }
                        onChange={(event) =>
                          setProgressDrafts((current) => ({
                            ...current,
                            [entry.opportunity.id]: {
                              stage:
                                current[entry.opportunity.id]?.stage ??
                                entry.application_stage,
                              next_action:
                                current[entry.opportunity.id]?.next_action ??
                                entry.next_action,
                              next_action_at: event.target.value,
                            },
                          }))
                        }
                      />
                    </label>
                    {!runtime.read_only && (
                      <button
                        className="button primary small"
                        disabled={savingProgress === entry.opportunity.id}
                        onClick={() => saveProgress(entry)}
                      >
                        {savingProgress === entry.opportunity.id
                          ? "保存中…"
                          : "保存进度"}
                      </button>
                    )}
                  </div>
                </div>
                {!entry.ready && entry.blockers.length > 0 && (
                  <div className="shortlist-blockers">
                    <strong>恢复到可投状态前需处理：</strong>
                    <ul>
                      {entry.blockers.map((blocker) => (
                        <li key={blocker}>{blocker}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {entry.note && <p className="shortlist-note">{entry.note}</p>}
                <div className="card-footer">
                  <NavLink
                    className="button secondary small"
                    to={`/jobs/${entry.opportunity.id}`}
                  >
                    {entry.ready ? "查看证据" : "处理阻断项"}
                  </NavLink>
                  {entry.ready && entry.opportunity.apply_url && (
                    <a
                      className="text-link"
                      href={entry.opportunity.apply_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {isConfirmedOfficialLink(entry.opportunity)
                        ? "打开官网"
                        : "打开来源链接"}{" "}
                      <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              </div>
              <button
                className="icon-button danger-icon"
                aria-label={`从短名单移除 ${entry.opportunity.title}`}
                disabled={
                  runtime.read_only || removing === entry.opportunity.id
                }
                onClick={() => remove(entry.opportunity.id)}
              >
                <Trash2 size={17} />
              </button>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<ListChecks />}
          title="可信短名单还是空的"
          description="先在具体岗位详情中完成官网核验。招聘项目线索、硬条件未知或官网未确认的记录不能加入。"
          action={
            <NavLink className="button primary" to="/verify">
              开始核验岗位
            </NavLink>
          }
        />
      )}
    </>
  );
}

const APPLICATION_STAGES: Array<{
  value: ApplicationStage;
  label: string;
}> = [
  { value: "TO_APPLY", label: "待投递" },
  { value: "APPLIED", label: "已投递" },
  { value: "ASSESSMENT", label: "笔试/测评" },
  { value: "INTERVIEW", label: "面试" },
  { value: "OFFER", label: "Offer" },
  { value: "REJECTED", label: "已结束" },
  { value: "WITHDRAWN", label: "主动放弃" },
];

function toDateInput(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}
