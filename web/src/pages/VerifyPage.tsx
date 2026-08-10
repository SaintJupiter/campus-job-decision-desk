import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  GitCompareArrows,
  SearchCheck,
  Split,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { NavLink } from "react-router-dom";

import {
  api,
  type DuplicateCandidate,
  type PaginatedOpportunities,
} from "../api";
import {
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  OpportunityCard,
  PageHeader,
  SectionHeading,
} from "../components";
import { useRemote } from "../useRemote";
import { useRuntime } from "../runtime";

const PAGE_SIZE = 30;

export function VerifyPage() {
  const [page, setPage] = useState(1);
  const opportunities = useRemote(
    () =>
      api<PaginatedOpportunities>(
        `/api/workspace/decision-queue?queue=verify_first&page=${page}&page_size=${PAGE_SIZE}`,
      ),
    [page],
  );
  const duplicates = useRemote(() =>
    api<DuplicateCandidate[]>(
      "/api/opportunities/review/duplicates?decision=REVIEW&limit=50",
    ),
  );
  const queue = opportunities.data?.items ?? [];
  const pageCount = Math.max(
    1,
    Math.ceil((opportunities.data?.total ?? 0) / PAGE_SIZE),
  );

  return (
    <>
      <PageHeader
        eyebrow="HUMAN-IN-THE-LOOP VERIFICATION"
        title="核验工作台"
        description="优先处理会改变投递决定的未知项、来源冲突、招聘项目拆分和重复候选。"
      />
      <div className="notice info">
        <SearchCheck size={19} />
        <div>
          <strong>核验结果保留五种状态</strong>
          <p>
            官网在招、官网明确关闭、页面未找到、访问受阻、尚无法判断。后面三种不会被系统改写为“已关闭”。
          </p>
        </div>
      </div>

      <section className="content-section queue-section">
        <SectionHeading
          title="待核验队列"
          description={`${opportunities.data?.total ?? 0} 条优先事项；招聘项目线索需要先找到官方具体岗位。`}
        />
        {opportunities.loading ? (
          <LoadingBlock />
        ) : opportunities.error ? (
          <ErrorBlock
            message={opportunities.error}
            onRetry={opportunities.reload}
          />
        ) : queue.length ? (
          <>
            <div className="opportunity-list">
              {queue.map((item) => (
                <OpportunityCard key={item.id} item={item} />
              ))}
            </div>
            <nav className="pagination" aria-label="核验队列分页">
              <button
                className="button secondary small"
                disabled={page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                <ChevronLeft size={16} />
                上一页
              </button>
              <span>
                第 {page} / {pageCount} 页
              </span>
              <button
                className="button secondary small"
                disabled={page >= pageCount}
                onClick={() =>
                  setPage((value) => Math.min(pageCount, value + 1))
                }
              >
                下一页
                <ChevronRight size={16} />
              </button>
            </nav>
          </>
        ) : (
          <EmptyState
            title="待核验队列为空"
            description="新导入的招聘项目、冲突和官网状态未知岗位会出现在这里。"
          />
        )}
      </section>

      <section className="content-section">
        <SectionHeading
          title="重复候选"
          description="相似只产生候选，不自动合并；官方岗位 ID 冲突时必须分开。"
        />
        {duplicates.loading ? (
          <LoadingBlock />
        ) : duplicates.error ? (
          <ErrorBlock message={duplicates.error} onRetry={duplicates.reload} />
        ) : duplicates.data?.length ? (
          <div className="duplicate-list">
            {duplicates.data.map((candidate) => (
              <DuplicateReview
                key={candidate.id}
                candidate={candidate}
                onSaved={duplicates.reload}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<GitCompareArrows />}
            title="没有待处理的重复候选"
            description="批次物化和去重建议运行后，相似岗位会进入人工复核队列。"
          />
        )}
      </section>
    </>
  );
}

function DuplicateReview({
  candidate,
  onSaved,
}: {
  candidate: DuplicateCandidate;
  onSaved: () => void;
}) {
  const runtime = useRuntime();
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  async function decide(decision: "MERGE" | "SEPARATE") {
    if (runtime.read_only) return;
    setMessage("");
    if (reason.trim().length < 2) {
      setMessage("请先填写至少 2 个字的判断依据");
      return;
    }
    setSaving(true);
    try {
      await api(`/api/opportunities/review/duplicates/${candidate.id}`, {
        method: "PATCH",
        body: JSON.stringify({ decision, reason }),
      });
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }
  return (
    <article className="duplicate-card">
      <div className="duplicate-score">
        <AlertTriangle size={17} />
        <span>相似度候选</span>
        <strong>{candidate.score.toFixed(2)}</strong>
      </div>
      <div className="duplicate-pair">
        {[candidate.left, candidate.right].map((item, index) =>
          item ? (
            <NavLink
              key={item.id}
              to={`/jobs/${item.id}`}
              className="duplicate-side"
            >
              <span>{index === 0 ? "记录 A" : "记录 B"}</span>
              <strong>{item.title || "未命名"}</strong>
              <small>
                {item.kind === "POSTING" ? "具体岗位" : "招聘项目"} ·{" "}
                {item.official_job_id || "无官方 ID"}
              </small>
            </NavLink>
          ) : (
            <div key={index} className="duplicate-side">
              <span>记录缺失</span>
            </div>
          ),
        )}
      </div>
      <label className="inline-reason">
        <span>判断依据</span>
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="例如：官方岗位 ID 不同，必须分开"
        />
      </label>
      {message && (
        <p className="form-error" role="alert">
          {message}
        </p>
      )}
      <div className="duplicate-actions">
        <button
          className="button secondary small"
          disabled={runtime.read_only || saving}
          onClick={() => decide("SEPARATE")}
        >
          <Split size={15} />
          保留为两个岗位
        </button>
        <button
          className="button danger small"
          disabled={runtime.read_only || saving}
          onClick={() => decide("MERGE")}
        >
          <GitCompareArrows size={15} />
          确认合并
        </button>
      </div>
      <p className="danger-hint">
        <XCircle size={14} />
        合并会变更数据关系；系统仍保留原始来源记录。
      </p>
    </article>
  );
}
