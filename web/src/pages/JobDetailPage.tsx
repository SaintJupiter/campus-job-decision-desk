import {
  ArrowLeft,
  CheckCircle2,
  CircleHelp,
  ExternalLink,
  FileText,
  History,
  Link2,
  ListPlus,
  Save,
  SearchCheck,
  ShieldCheck,
  Split,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, useParams } from "react-router-dom";

import {
  api,
  displayValue,
  humanDate,
  isConfirmedOfficialLink,
  type Claim,
  type Decision,
  type OpportunityDetail,
  type ReviewDecision,
  type VerificationResult,
} from "../api";
import {
  EligibilityBadge,
  EmptyState,
  ErrorBlock,
  FitBadge,
  KindBadge,
  LoadingBlock,
  PageHeader,
  SectionHeading,
  TrustBadge,
  VerificationBadge,
} from "../components";
import { useRuntime } from "../runtime";
import { useRemote } from "../useRemote";

const fieldLabels: Record<string, string> = {
  company: "公司",
  title: "岗位名称",
  cities: "城市",
  graduation_years: "毕业届次",
  education: "学历",
  recruitment_type: "招聘类型",
  deadline: "截止时间",
  status: "开放状态",
  announcement_url: "公告链接",
  apply_url: "投递链接",
  official_job_id: "官方岗位 ID",
};

function claimDisplayValue(claim: Claim) {
  try {
    return displayValue(JSON.parse(claim.raw_value));
  } catch {
    return displayValue(claim.raw_value || claim.normalized_value);
  }
}

const axisCopy = {
  eligibility: {
    title: "可投性",
    description: "只判断届次、学历、城市、招聘类型和开放状态等硬条件。",
  },
  evidence_fit: {
    title: "经历证据",
    description: "只引用已确认的简历事实，不把相似经历包装成直接经验。",
  },
  trust: {
    title: "信息可信度",
    description: "区分官网核验、多源一致、冲突、陈旧和无法判断。",
  },
};

export function JobDetailPage() {
  const runtime = useRuntime();
  const { id = "" } = useParams();
  const detail = useRemote(
    () => api<OpportunityDetail>(`/api/opportunities/${id}`),
    [id],
  );
  const [notice, setNotice] = useState("");

  if (detail.loading) return <LoadingBlock label="正在读取岗位证据…" />;
  if (detail.error)
    return <ErrorBlock message={detail.error} onRetry={detail.reload} />;
  if (!detail.data)
    return (
      <EmptyState title="岗位不存在" description="该记录可能已经合并或删除。" />
    );

  const item = detail.data.item;
  const latest = item.decision_current
    ? detail.data.decision_history.find((decision) => decision.is_current)
    : undefined;
  const shortlistBlockers = shortlistKnownBlockers(item, latest);

  async function addShortlist() {
    if (runtime.read_only) return;
    setNotice("");
    try {
      await api(`/api/workspace/shortlist/${item.id}`, {
        method: "POST",
        body: JSON.stringify({ priority: 50, note: "" }),
      });
      setNotice("已加入可信短名单");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "加入失败");
    }
  }

  return (
    <>
      <NavLink className="back-link" to="/jobs">
        <ArrowLeft size={16} />
        返回岗位池
      </NavLink>
      <PageHeader
        eyebrow={
          item.kind === "CAMPAIGN"
            ? "RECRUITMENT CAMPAIGN"
            : "SPECIFIC JOB POSTING"
        }
        title={item.title || "未命名岗位线索"}
        description={`${item.company || "公司待确认"} · ${item.cities.join("、") || "城市待确认"}`}
        actions={
          <>
            {item.kind === "POSTING" && item.apply_url && (
              <a
                className="button secondary"
                href={item.apply_url}
                target="_blank"
                rel="noreferrer"
              >
                {isConfirmedOfficialLink(item) ? "打开官网" : "打开来源链接"}{" "}
                <ExternalLink size={16} />
              </a>
            )}
            {item.kind === "POSTING" && (
              <button
                className="button primary"
                onClick={addShortlist}
                disabled={runtime.read_only || shortlistBlockers.length > 0}
                title={shortlistBlockers.join("；")}
              >
                <ListPlus size={16} />
                {shortlistBlockers.length
                  ? "证据未达到短名单门槛"
                  : "加入可信短名单"}
              </button>
            )}
          </>
        }
      />
      {notice && (
        <div className="notice info" role="status">
          <CircleHelp size={18} />
          <span>{notice}</span>
        </div>
      )}

      <section className="detail-summary panel">
        <div className="summary-title">
          <KindBadge kind={item.kind} />
          {item.title_inferred && (
            <span className="mono-chip">岗位方向推断 · 非官方名称</span>
          )}
          <VerificationBadge value={item.verification} />
          {item.official_job_id && (
            <span className="mono-chip">ID {item.official_job_id}</span>
          )}
        </div>
        {item.title_inferred && item.source_title && (
          <div className="notice info inferred-source-title">
            <CircleHelp size={17} />
            <span>
              <strong>聚合表原始表述：</strong>
              {item.source_title}。{item.title_inference_reason}
            </span>
          </div>
        )}
        <dl className="fact-summary">
          <div>
            <dt>毕业届次</dt>
            <dd>{item.graduation_years.join("、") || "待确认"}</dd>
          </div>
          <div>
            <dt>招聘类型</dt>
            <dd>{item.recruitment_type || "待确认"}</dd>
          </div>
          <div>
            <dt>企业性质</dt>
            <dd>{item.employer_type || "待确认"}</dd>
          </div>
          <div>
            <dt>笔试要求</dt>
            <dd>{item.written_test || "未说明"}</dd>
          </div>
          <div>
            <dt>截止时间</dt>
            <dd>{item.deadline || "未明确"}</dd>
          </div>
          <div>
            <dt>独立来源 / 原始观察</dt>
            <dd>
              {item.source_count} /{" "}
              {item.observation_count ?? item.source_count}
            </dd>
          </div>
          <div>
            <dt>字段冲突</dt>
            <dd>{item.conflict_count} 项</dd>
          </div>
          <div>
            <dt>最近更新</dt>
            <dd>{humanDate(item.updated_at, true)}</dd>
          </div>
        </dl>
        <ClassificationForm
          opportunityId={item.id}
          currentKind={item.kind}
          readOnly={runtime.read_only}
          onSaved={detail.reload}
        />
      </section>

      {item.kind === "POSTING" && shortlistBlockers.length > 0 && (
        <div className="notice warning shortlist-readiness">
          <CircleHelp size={19} />
          <div>
            <strong>暂时不能加入可信短名单</strong>
            <p>
              {shortlistBlockers.join("；")}。服务器还会检查决策版本与 14
              天核验时效。
            </p>
          </div>
        </div>
      )}

      {item.kind === "CAMPAIGN" && (
        <div className="notice warning">
          <SearchCheck size={20} />
          <div>
            <strong>这是一条招聘项目线索，不能直接投递</strong>
            <p>
              公司项目包含上海或“产品类”，不代表某个具体岗位也满足这些条件。请先关联官方
              具体岗位。
            </p>
          </div>
        </div>
      )}

      <section className="content-section">
        <SectionHeading
          title="三轴决策"
          description="高经历匹配不能抵消硬条件失败，来源一致也不等于官网已核验。"
        />
        {latest ? (
          <div className="axis-grid">
            <AxisPanel axis="eligibility" decision={latest} />
            <AxisPanel axis="evidence_fit" decision={latest} />
            <AxisPanel axis="trust" decision={latest} />
          </div>
        ) : (
          <EmptyState
            title={item.needs_recompute ? "决策证据已变化" : "还没有系统决策"}
            description={
              item.needs_recompute
                ? "画像、偏好或岗位证据已更新，历史结果不再用于当前决策，请重新计算。"
                : "确认画像事实并保存一次官网核验后，系统会生成可解释的三轴结果。"
            }
          />
        )}
      </section>

      <section className="content-section">
        <SectionHeading
          title="字段证据矩阵"
          description="每个值保留来源、观察时间和采用理由；官网只覆盖其明确声明的字段。"
        />
        <ClaimMatrix claims={detail.data.claims} />
      </section>

      <div className="detail-columns">
        <section className="content-section">
          <SectionHeading
            title="官网核验"
            description="页面未找到或访问受阻，都不等于岗位关闭。"
          />
          {!item.official_domain_verified && (
            <OfficialDomainForm
              opportunityId={item.id}
              candidateDomain={item.candidate_domain}
              onSaved={detail.reload}
              readOnly={runtime.read_only}
            />
          )}
          {item.official_domain_verified && (
            <div className="notice success compact-notice">
              <ShieldCheck size={17} />
              <span>
                已确认官网范围：{item.official_domain}
                {item.official_scope_path}
              </span>
            </div>
          )}
          {item.official_domain_verified && !item.official_job_id && (
            <OfficialIdentityForm
              opportunityId={item.id}
              defaultUrl={item.apply_url}
              onSaved={detail.reload}
              readOnly={runtime.read_only}
            />
          )}
          {item.official_domain_verified && item.official_job_id && (
            <VerificationForm
              opportunityId={item.id}
              onSaved={detail.reload}
              defaultUrl={item.apply_url}
              readOnly={runtime.read_only}
            />
          )}
          <VerificationHistory items={detail.data.verifications} />
        </section>
        <section className="content-section">
          <SectionHeading
            title="人工决策"
            description="人工可以覆盖系统建议，但必须留下原因。"
          />
          <ManualDecisionForm
            opportunityId={item.id}
            decision={latest}
            onSaved={detail.reload}
            readOnly={runtime.read_only}
          />
          {item.kind === "CAMPAIGN" && (
            <CampaignLinkForm
              campaignId={item.id}
              linkedPostings={detail.data.linked_postings}
              onSaved={detail.reload}
              readOnly={runtime.read_only}
            />
          )}
          {item.kind === "POSTING" &&
            detail.data.linked_campaigns.length > 0 && (
              <div className="linked-records">
                <h3>关联招聘项目</h3>
                {detail.data.linked_campaigns.map((campaignId) => (
                  <NavLink key={campaignId} to={`/jobs/${campaignId}`}>
                    <Link2 size={14} />
                    {campaignId}
                  </NavLink>
                ))}
              </div>
            )}
        </section>
      </div>

      <section className="content-section">
        <SectionHeading
          title="原始来源记录"
          description="规范化不会覆盖购买表或聚合表中的原始内容。"
        />
        {detail.data.origins.length ? (
          <div className="origin-list">
            {detail.data.origins.map((origin) => (
              <details key={origin.raw_record_id} className="origin-record">
                <summary>
                  <span>
                    <FileText size={16} />
                    {origin.source_name || "未知来源"} · 第 {origin.row_number}{" "}
                    行
                  </span>
                  <span>{origin.file_name}</span>
                </summary>
                <pre>{JSON.stringify(origin.raw_payload, null, 2)}</pre>
              </details>
            ))}
          </div>
        ) : (
          <EmptyState
            title="没有可展示的原始记录"
            description="当前岗位可能由人工创建，或来源记录尚未关联。"
          />
        )}
      </section>
    </>
  );
}

function shortlistKnownBlockers(
  item: OpportunityDetail["item"],
  decision?: Decision,
) {
  const blockers: string[] = [];
  if (item.kind !== "POSTING") blockers.push("招聘项目线索不能直接投递");
  if (!decision)
    blockers.push(
      item.needs_recompute
        ? "画像或岗位证据已变化，请重新计算"
        : "尚未计算三轴决策",
    );
  else {
    if (decision.eligibility !== "PASS") blockers.push("硬条件尚未明确通过");
    if (
      decision.trust !== "VERIFIED" &&
      decision.trust !== "VERIFIED_WITH_CONFLICT"
    )
      blockers.push("信息可信度尚未达到官网核验");
    if (["HOLD", "REJECT"].includes(decision.manual_decision))
      blockers.push("人工决策为暂缓或排除");
  }
  if (item.verification !== "OPEN") blockers.push("最新官网核验不是在招");
  return blockers;
}

function OfficialDomainForm({
  opportunityId,
  candidateDomain,
  onSaved,
  readOnly,
}: {
  opportunityId: string;
  candidateDomain: string;
  onSaved: () => void;
  readOnly: boolean;
}) {
  const [domain, setDomain] = useState(candidateDomain);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (readOnly || saving) return;
    setSaving(true);
    setMessage("");
    try {
      await api(`/api/opportunities/${opportunityId}/official-domain`, {
        method: "PATCH",
        body: JSON.stringify({ domain, reason }),
      });
      setMessage("官方招聘域名已确认");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "确认失败");
    } finally {
      setSaving(false);
    }
  }
  return (
    <form className="stack-form trust-anchor-form" onSubmit={submit}>
      <div className="notice warning compact-notice">
        <CircleHelp size={17} />
        <span>
          导入链接只是候选线索。请在公司主站确认；共享 ATS
          必须粘贴含公司租户路径的招聘页。
        </span>
      </div>
      <label>
        <span>官方招聘域名或租户页面</span>
        <input
          disabled={readOnly || saving}
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          placeholder="careers.example.com 或 https://jobs.lever.co/company"
          required
        />
      </label>
      <label>
        <span>确认依据</span>
        <textarea
          disabled={readOnly || saving}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="例如：从公司主站的“加入我们”导航进入该域名。"
          minLength={4}
          required
        />
      </label>
      {message && (
        <p className="form-message" role="status">
          {message}
        </p>
      )}
      <button
        className="button secondary"
        type="submit"
        disabled={readOnly || saving}
      >
        <ShieldCheck size={16} />
        {saving ? "正在确认…" : "确认为官方域名"}
      </button>
    </form>
  );
}

function OfficialIdentityForm({
  opportunityId,
  defaultUrl,
  onSaved,
  readOnly,
}: {
  opportunityId: string;
  defaultUrl: string;
  onSaved: () => void;
  readOnly: boolean;
}) {
  const [jobId, setJobId] = useState("");
  const [url, setUrl] = useState(defaultUrl);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (readOnly || saving) return;
    setSaving(true);
    setMessage("");
    try {
      await api(`/api/opportunities/${opportunityId}/official-identity`, {
        method: "PATCH",
        body: JSON.stringify({ official_job_id: jobId, url, reason }),
      });
      setMessage("具体岗位身份已绑定，现在可以核验开放状态");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "身份绑定失败");
    } finally {
      setSaving(false);
    }
  }
  return (
    <form className="stack-form identity-binding-form" onSubmit={submit}>
      <div className="notice warning compact-notice">
        <CircleHelp size={17} />
        <span>
          当前记录还没有官方岗位 ID。先从具体岗位 URL
          确认身份，防止把同公司其他岗位错绑到当前记录。
        </span>
      </div>
      <label>
        <span>官方岗位 ID</span>
        <input
          disabled={readOnly || saving}
          value={jobId}
          onChange={(event) => setJobId(event.target.value)}
          placeholder="例如 A110957"
          required
        />
      </label>
      <label>
        <span>官方具体岗位 URL</span>
        <input
          type="url"
          disabled={readOnly || saving}
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
        />
      </label>
      <label>
        <span>身份确认依据</span>
        <textarea
          disabled={readOnly || saving}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="例如：URL 路径中的 ID 与页面岗位编号一致。"
          minLength={4}
          required
        />
      </label>
      {message && (
        <p className="form-message" role="status">
          {message}
        </p>
      )}
      <button
        className="button secondary"
        type="submit"
        disabled={readOnly || saving}
      >
        <Link2 size={16} />
        {saving ? "正在绑定…" : "绑定具体岗位身份"}
      </button>
    </form>
  );
}

function ClassificationForm({
  opportunityId,
  currentKind,
  onSaved,
  readOnly,
}: {
  opportunityId: string;
  currentKind: "CAMPAIGN" | "POSTING";
  onSaved: () => void;
  readOnly: boolean;
}) {
  const [kind, setKind] = useState(currentKind);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => setKind(currentKind), [currentKind]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (readOnly) return;
    if (kind === currentKind) {
      setMessage("分类没有变化");
      return;
    }
    if (reason.trim().length < 4) {
      setMessage("请用至少 4 个字说明改判证据");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      await api(`/api/opportunities/${opportunityId}/classification`, {
        method: "PATCH",
        body: JSON.stringify({ kind, reason }),
      });
      setReason("");
      setMessage("分类已更新，三轴决策正在按新类型重算");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "分类更新失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="classification-editor">
      <summary>
        <Split size={14} />
        这条记录分类不对？人工纠正
      </summary>
      <form className="classification-form" onSubmit={submit}>
        <label>
          <span>记录类型</span>
          <select
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as "CAMPAIGN" | "POSTING")
            }
          >
            <option value="CAMPAIGN">招聘项目（Campaign）</option>
            <option value="POSTING">具体岗位（Posting）</option>
          </select>
        </label>
        <label>
          <span>改判证据</span>
          <input
            value={reason}
            minLength={4}
            onChange={(event) => setReason(event.target.value)}
            placeholder="例如：页面包含岗位职责与唯一职位 ID"
          />
        </label>
        <button
          className="button secondary small"
          disabled={readOnly || saving || kind === currentKind}
        >
          <Save size={14} />
          {saving ? "保存中…" : "保存分类"}
        </button>
      </form>
      {kind === "CAMPAIGN" && currentKind === "POSTING" && (
        <p className="form-hint">改为招聘项目后，该记录会从可信短名单移除。</p>
      )}
      {message && (
        <p className="form-message" role="status">
          {message}
        </p>
      )}
    </details>
  );
}

function AxisPanel({
  axis,
  decision,
}: {
  axis: "eligibility" | "evidence_fit" | "trust";
  decision: Decision;
}) {
  const reasons = decision.reasons.filter(
    (item) => item.axis === axis || !item.axis,
  );
  const unknowns = decision.unknowns.filter(
    (item) => item.axis === axis || !item.axis,
  );
  return (
    <article className="axis-panel">
      <div className="axis-panel-title">
        <div>
          <span>{axisCopy[axis].title}</span>
          {axis === "eligibility" && (
            <EligibilityBadge value={decision.eligibility} />
          )}
          {axis === "evidence_fit" && (
            <FitBadge value={decision.evidence_fit} />
          )}
          {axis === "trust" && <TrustBadge value={decision.trust} />}
        </div>
      </div>
      <p className="axis-description">{axisCopy[axis].description}</p>
      <ul className="reason-list">
        {reasons.map((reason, index) => (
          <li key={`${reason.code}-${index}`}>
            <CheckCircle2 size={15} />
            <span>{reason.message}</span>
          </li>
        ))}
        {unknowns.map((unknown, index) => (
          <li key={`${unknown.code}-${index}`} className="is-unknown">
            <CircleHelp size={15} />
            <span>{unknown.message}</span>
          </li>
        ))}
      </ul>
      {axis === "evidence_fit" && decision.evidence_links.length > 0 && (
        <div className="evidence-quotes">
          {Array.from(
            new Map(
              decision.evidence_links.map((evidence) => [
                evidence.evidence_text.trim(),
                evidence,
              ]),
            ).values(),
          )
            .slice(0, 3)
            .map((evidence) => (
              <blockquote key={evidence.fact_id}>
                <strong>{evidence.value}</strong>
                <span>“{evidence.evidence_text}”</span>
              </blockquote>
            ))}
        </div>
      )}
    </article>
  );
}

function ClaimMatrix({ claims }: { claims: Claim[] }) {
  const groups = useMemo(() => {
    const value = new Map<string, Claim[]>();
    for (const claim of claims)
      value.set(claim.field_name, [
        ...(value.get(claim.field_name) ?? []),
        claim,
      ]);
    return [...value.entries()];
  }, [claims]);
  if (!groups.length)
    return (
      <EmptyState
        title="没有字段级证据"
        description="导入来源记录或保存官网核验后，证据会按字段出现在这里。"
      />
    );
  return (
    <div className="table-wrap">
      <table className="evidence-table">
        <thead>
          <tr>
            <th>字段</th>
            <th>当前值 / 来源值</th>
            <th>来源与权威级别</th>
            <th>观察时间</th>
            <th>处理状态</th>
          </tr>
        </thead>
        <tbody>
          {groups.flatMap(([field, fieldClaims]) =>
            fieldClaims.map((claim, index) => (
              <tr
                key={claim.id}
                className={claim.selected ? "is-selected" : undefined}
              >
                {index === 0 && (
                  <th scope="row" rowSpan={fieldClaims.length}>
                    {fieldLabels[field] ?? field}
                  </th>
                )}
                <td>{claimDisplayValue(claim)}</td>
                <td>
                  <strong>
                    {claim.source_name || claim.evidence_label || "未知来源"}
                  </strong>
                  <span>Authority {claim.authority}</span>
                  {claim.evidence_url && (
                    <a
                      href={claim.evidence_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      查看证据 <ExternalLink size={12} />
                    </a>
                  )}
                </td>
                <td>{humanDate(claim.observed_at, true)}</td>
                <td>
                  {!claim.applicable ? (
                    <span>历史证据 · 当前粒度不适用</span>
                  ) : claim.selected ? (
                    <span className="selected-claim">
                      <ShieldCheck size={14} />
                      当前采用
                    </span>
                  ) : (
                    <span>历史说法</span>
                  )}
                  {claim.resolution_reason && (
                    <small>{claim.resolution_reason}</small>
                  )}
                </td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}

function VerificationForm({
  opportunityId,
  defaultUrl,
  onSaved,
  readOnly,
}: {
  opportunityId: string;
  defaultUrl: string;
  onSaved: () => void;
  readOnly: boolean;
}) {
  const [result, setResult] = useState<VerificationResult>("OPEN");
  const [url, setUrl] = useState(defaultUrl);
  const [excerpt, setExcerpt] = useState("");
  const [city, setCity] = useState("");
  const [graduation, setGraduation] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (readOnly) return;
    setSaving(true);
    setError("");
    const extracted_fields: Record<string, unknown> = {};
    if (city.trim())
      extracted_fields.cities = city
        .split(/[\u3001,，]/)
        .map((item) => item.trim())
        .filter(Boolean);
    if (graduation.trim())
      extracted_fields.graduation_years = graduation
        .split(/[\u3001,，]/)
        .map((item) => item.trim())
        .filter(Boolean);
    try {
      await api(`/api/opportunities/${opportunityId}/verifications`, {
        method: "POST",
        body: JSON.stringify({
          result,
          url,
          evidence_excerpt: excerpt,
          extracted_fields,
          reviewer: "user",
        }),
      });
      setExcerpt("");
      setCity("");
      setGraduation("");
      onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="stack-form" onSubmit={submit}>
      <div className="form-grid two">
        <label>
          <span>核验结果</span>
          <select
            value={result}
            onChange={(event) =>
              setResult(event.target.value as VerificationResult)
            }
          >
            <option value="OPEN">官网在招</option>
            <option value="CLOSED">官网明确关闭</option>
            <option value="NOT_FOUND">页面未找到</option>
            <option value="BLOCKED">访问受阻</option>
            <option value="UNKNOWN">尚无法判断</option>
          </select>
        </label>
        <label>
          <span>官网 URL</span>
          <input
            type="url"
            required
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://…"
          />
        </label>
      </div>
      <label>
        <span>页面证据</span>
        <textarea
          value={excerpt}
          onChange={(event) => setExcerpt(event.target.value)}
          placeholder="只记录页面明确显示的内容，例如：具体岗位页显示申请按钮。"
        />
      </label>
      <div className="form-grid two">
        <label>
          <span>官网明确城市（可选）</span>
          <input
            value={city}
            onChange={(event) => setCity(event.target.value)}
            placeholder="上海、杭州"
          />
        </label>
        <label>
          <span>官网明确届次（可选）</span>
          <input
            value={graduation}
            onChange={(event) => setGraduation(event.target.value)}
            placeholder="2027届"
          />
        </label>
      </div>
      <p className="form-hint">
        未填写的字段保持未知，不会被官网链接自动补全。
      </p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <button className="button primary" disabled={readOnly || saving}>
        <Save size={16} />
        {saving ? "保存中…" : "保存核验并重算"}
      </button>
    </form>
  );
}

function VerificationHistory({
  items,
}: {
  items: OpportunityDetail["verifications"];
}) {
  return (
    <div className="history-list">
      <h3>
        <History size={16} />
        核验历史
      </h3>
      {items.length ? (
        items.map((item) => (
          <article key={item.id} className="history-item">
            <div>
              <VerificationBadge value={item.result} />
              <span className="mono-chip">
                {item.evidence_scope === "POSTING"
                  ? "具体岗位证据"
                  : item.evidence_scope === "CAMPAIGN"
                    ? "招聘项目证据"
                    : "历史证据范围未知"}
              </span>
              <time>{humanDate(item.checked_at, true)}</time>
            </div>
            <p>{item.evidence_excerpt || "未记录页面摘录"}</p>
            <a
              href={item.final_url || item.url}
              target="_blank"
              rel="noreferrer"
            >
              查看当时链接 <ExternalLink size={12} />
            </a>
          </article>
        ))
      ) : (
        <p className="muted">尚未进行官网核验。</p>
      )}
    </div>
  );
}

function ManualDecisionForm({
  opportunityId,
  decision,
  onSaved,
  readOnly,
}: {
  opportunityId: string;
  decision?: Decision;
  onSaved: () => void;
  readOnly: boolean;
}) {
  const [value, setValue] = useState<ReviewDecision>(
    decision?.manual_decision ?? "UNDECIDED",
  );
  const [reason, setReason] = useState(decision?.override_reason ?? "");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setValue(decision?.manual_decision ?? "UNDECIDED");
    setReason(decision?.override_reason ?? "");
  }, [decision]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (readOnly || saving) return;
    setSaving(true);
    setMessage("");
    try {
      await api(`/api/opportunities/${opportunityId}/decision`, {
        method: "PATCH",
        body: JSON.stringify({ decision: value, reason }),
      });
      setMessage("人工决策已保存");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }
  return (
    <form className="stack-form" onSubmit={submit}>
      <label>
        <span>最终人工决定</span>
        <select
          disabled={readOnly || saving}
          value={value}
          onChange={(event) => setValue(event.target.value as ReviewDecision)}
        >
          <option value="UNDECIDED">尚未决定</option>
          <option value="PREPARE_APPLY">准备投递</option>
          <option value="VERIFY_FIRST">先核验</option>
          <option value="HOLD">暂缓</option>
          <option value="REJECT">排除</option>
        </select>
      </label>
      <label>
        <span>决定理由</span>
        <textarea
          disabled={readOnly || saving}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="例如：岗位偏客户交付，不符合当前工作偏好。"
        />
      </label>
      {message && (
        <p className="form-message" role="status">
          {message}
        </p>
      )}
      <button className="button secondary" disabled={readOnly || saving}>
        <Save size={16} />
        {saving ? "正在保存…" : "保存人工决定"}
      </button>
    </form>
  );
}

function CampaignLinkForm({
  campaignId,
  linkedPostings,
  onSaved,
  readOnly,
}: {
  campaignId: string;
  linkedPostings: string[];
  onSaved: () => void;
  readOnly: boolean;
}) {
  const [postingId, setPostingId] = useState("");
  const [evidence, setEvidence] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (readOnly || saving) return;
    setSaving(true);
    setMessage("");
    try {
      await api(`/api/opportunities/${campaignId}/postings`, {
        method: "POST",
        body: JSON.stringify({
          posting_id: postingId,
          evidence,
          confidence: 1,
        }),
      });
      setPostingId("");
      setEvidence("");
      setMessage("具体岗位已关联");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "关联失败");
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="campaign-link-block">
      <h3>
        <Link2 size={16} />
        关联具体岗位
      </h3>
      <form className="stack-form" onSubmit={submit}>
        <label>
          <span>具体岗位 ID</span>
          <input
            required
            disabled={readOnly || saving}
            value={postingId}
            onChange={(event) => setPostingId(event.target.value)}
            placeholder="从岗位详情 URL 复制 ID"
          />
        </label>
        <label>
          <span>关联证据</span>
          <textarea
            required
            disabled={readOnly || saving}
            minLength={2}
            value={evidence}
            onChange={(event) => setEvidence(event.target.value)}
            placeholder="说明为什么它属于该招聘项目。"
          />
        </label>
        {message && (
          <p className="form-message" role="status">
            {message}
          </p>
        )}
        <button className="button secondary" disabled={readOnly || saving}>
          <Link2 size={15} />
          {saving ? "正在关联…" : "确认关联"}
        </button>
      </form>
      {linkedPostings.length > 0 && (
        <div className="linked-records">
          {linkedPostings.map((id) => (
            <NavLink key={id} to={`/jobs/${id}`}>
              {id}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}
