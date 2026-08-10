import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Filter,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  api,
  queryString,
  type Eligibility,
  type OpportunityKind,
  type PaginatedOpportunities,
  type Profile,
  type Trust,
} from "../api";
import {
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  OpportunityCard,
  PageHeader,
} from "../components";
import { useRemote } from "../useRemote";

const PAGE_SIZE = 20;

export function JobsPage() {
  const [searchParams] = useSearchParams();
  const [draftSearch, setDraftSearch] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<OpportunityKind | "">("");
  const [city, setCity] = useState("");
  const [graduationYear, setGraduationYear] = useState("");
  const [recruitmentType, setRecruitmentType] = useState("");
  const [employerType, setEmployerType] = useState("");
  const [writtenTest, setWrittenTest] = useState("");
  const [deadlineWithin, setDeadlineWithin] = useState("");
  const [sort, setSort] = useState<"updated" | "deadline">("updated");
  const [eligibility, setEligibility] = useState<Eligibility | "">("");
  const [trust, setTrust] = useState<Trust | "">("");
  const [conflictOnly, setConflictOnly] = useState(
    searchParams.get("conflict_only") === "true",
  );
  const [page, setPage] = useState(1);
  const [profileDefaultsApplied, setProfileDefaultsApplied] = useState(false);
  const profile = useRemote(() => api<Profile>("/api/workspace/profile"));
  const request = queryString({
    page,
    page_size: PAGE_SIZE,
    search,
    kind,
    city,
    graduation_year: graduationYear,
    recruitment_type: recruitmentType,
    employer_type: employerType,
    written_test: writtenTest,
    deadline_within_days: deadlineWithin,
    sort,
    eligibility,
    trust,
    conflict_only: conflictOnly ? "true" : undefined,
  });
  const result = useRemote(
    () => api<PaginatedOpportunities>(`/api/opportunities?${request}`),
    [request],
  );

  useEffect(() => {
    if (profileDefaultsApplied || !profile.data) return;
    const cityPreference = profile.data.preferences.find(
      (item) => item.key === "accepted_cities",
    )?.value;
    const preferredCity = Array.isArray(cityPreference)
      ? String(cityPreference[0] ?? "")
      : "";
    const graduationFact = profile.data.facts.find(
      (fact) => fact.confirmed && fact.category === "GRADUATION_YEAR",
    );
    if (preferredCity) setCity(preferredCity);
    if (graduationFact?.label) {
      setGraduationYear(graduationFact.label.replace(/届$/u, ""));
    }
    setProfileDefaultsApplied(true);
  }, [profile.data, profileDefaultsApplied]);

  useEffect(
    () => setPage(1),
    [
      search,
      kind,
      city,
      graduationYear,
      recruitmentType,
      employerType,
      writtenTest,
      deadlineWithin,
      sort,
      eligibility,
      trust,
      conflictOnly,
    ],
  );
  const pageCount = Math.max(
    1,
    Math.ceil((result.data?.total ?? 0) / PAGE_SIZE),
  );

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    setSearch(draftSearch.trim());
  }

  return (
    <>
      <PageHeader
        eyebrow="OPPORTUNITY INBOX"
        title="岗位池"
        description="招聘项目与具体岗位分开处理；只有经过核验的官方具体岗位才能进入可信短名单。"
      />

      <section className="toolbar-panel">
        <form className="search-box" onSubmit={submitSearch} role="search">
          <Search size={18} aria-hidden="true" />
          <input
            value={draftSearch}
            onChange={(event) => setDraftSearch(event.target.value)}
            placeholder="搜索岗位名称"
            aria-label="搜索岗位名称"
          />
          <button className="button secondary small" type="submit">
            搜索
          </button>
        </form>
        <label className="select-control">
          <Filter size={16} aria-hidden="true" />
          <span className="sr-only">机会类型</span>
          <select
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as OpportunityKind | "")
            }
          >
            <option value="">全部类型</option>
            <option value="POSTING">具体岗位</option>
            <option value="CAMPAIGN">招聘项目线索</option>
          </select>
        </label>
        <label className="compact-field">
          <span>城市</span>
          <input
            value={city}
            onChange={(event) => setCity(event.target.value)}
            placeholder="上海"
          />
        </label>
        <label className="compact-field">
          <span>届次</span>
          <input
            value={graduationYear}
            onChange={(event) => setGraduationYear(event.target.value)}
            placeholder="2027"
          />
        </label>
        <label className="select-control compact-select">
          <span className="sr-only">硬条件判断</span>
          <select
            value={eligibility}
            onChange={(event) =>
              setEligibility(event.target.value as Eligibility | "")
            }
          >
            <option value="">全部资格</option>
            <option value="PASS">硬条件通过</option>
            <option value="UNKNOWN">资格待确认</option>
            <option value="FAIL">硬条件不符</option>
          </select>
        </label>
        <label className="select-control compact-select">
          <span className="sr-only">可信度</span>
          <select
            value={trust}
            onChange={(event) => setTrust(event.target.value as Trust | "")}
          >
            <option value="">全部可信度</option>
            <option value="VERIFIED">官网已核验</option>
            <option value="VERIFIED_WITH_CONFLICT">核验后仍有冲突</option>
            <option value="CONSISTENT">多源一致</option>
            <option value="CONFLICTED">来源冲突</option>
            <option value="STALE">证据陈旧</option>
            <option value="UNKNOWN">尚未核验</option>
          </select>
        </label>
        <label className="check-filter">
          <input
            type="checkbox"
            checked={conflictOnly}
            onChange={(event) => setConflictOnly(event.target.checked)}
          />
          只看冲突
        </label>
        <div className="result-count" aria-live="polite">
          {result.data
            ? `共 ${result.data.total.toLocaleString("zh-CN")} 条`
            : "正在统计"}
        </div>
      </section>

      <details className="domestic-filter-panel">
        <summary>
          <span>
            <SlidersHorizontal size={16} />
            更多校招筛选
          </span>
          <small>批次 · 企业性质 · 笔试 · 截止时间</small>
          <ChevronDown size={16} aria-hidden="true" />
        </summary>
        <div className="domestic-filter-controls" aria-label="国内校招筛选">
          <label className="select-control compact-select">
            <span className="sr-only">招聘批次</span>
            <select
              value={recruitmentType}
              onChange={(event) => setRecruitmentType(event.target.value)}
            >
              <option value="">全部批次</option>
              <option value="提前批">提前批</option>
              <option value="秋招">秋招</option>
              <option value="春招">春招</option>
              <option value="实习">日常/暑期实习</option>
            </select>
          </label>
          <label className="select-control compact-select">
            <span className="sr-only">企业性质</span>
            <select
              value={employerType}
              onChange={(event) => setEmployerType(event.target.value)}
            >
              <option value="">全部企业性质</option>
              <option value="央企">央企</option>
              <option value="国企">国企</option>
              <option value="民营">民营企业</option>
              <option value="外企">外企</option>
              <option value="事业单位">事业单位</option>
            </select>
          </label>
          <label className="select-control compact-select">
            <span className="sr-only">笔试要求</span>
            <select
              value={writtenTest}
              onChange={(event) => setWrittenTest(event.target.value)}
            >
              <option value="">全部笔试要求</option>
              <option value="免笔试">免笔试</option>
              <option value="笔试">有笔试</option>
            </select>
          </label>
          <label className="select-control compact-select">
            <span className="sr-only">截止时间</span>
            <select
              value={deadlineWithin}
              onChange={(event) => setDeadlineWithin(event.target.value)}
            >
              <option value="">全部截止时间</option>
              <option value="7">7 天内截止</option>
              <option value="14">14 天内截止</option>
              <option value="30">30 天内截止</option>
            </select>
          </label>
          <label className="select-control compact-select">
            <span className="sr-only">排序方式</span>
            <select
              value={sort}
              onChange={(event) =>
                setSort(event.target.value as "updated" | "deadline")
              }
            >
              <option value="updated">最近更新优先</option>
              <option value="deadline">临近截止优先</option>
            </select>
          </label>
        </div>
      </details>

      {result.loading ? (
        <LoadingBlock label="正在读取岗位池…" />
      ) : result.error ? (
        <ErrorBlock message={result.error} onRetry={result.reload} />
      ) : result.data?.items.length ? (
        <>
          <div className="opportunity-list-head" aria-hidden="true">
            <span>岗位与公司</span>
            <span>范围与来源</span>
            <span>投递判断</span>
            <span>下一步</span>
          </div>
          <div className="opportunity-list">
            {result.data.items.map((item) => (
              <OpportunityCard key={item.id} item={item} />
            ))}
          </div>
          <nav className="pagination" aria-label="岗位池分页">
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
              onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
            >
              下一页
              <ChevronRight size={16} />
            </button>
          </nav>
        </>
      ) : (
        <EmptyState
          title={
            search ||
            kind ||
            city ||
            graduationYear ||
            recruitmentType ||
            employerType ||
            writtenTest ||
            deadlineWithin ||
            sort !== "updated" ||
            eligibility ||
            trust ||
            conflictOnly
              ? "没有符合当前筛选的记录"
              : "岗位池还是空的"
          }
          description={
            search ||
            kind ||
            city ||
            graduationYear ||
            recruitmentType ||
            employerType ||
            writtenTest ||
            deadlineWithin ||
            sort !== "updated" ||
            eligibility ||
            trust ||
            conflictOnly
              ? "尝试清空搜索或切换机会类型。"
              : "先从数据来源页导入 CSV、XLSX、TSV 或 Markdown 岗位表。"
          }
          action={
            search ||
            kind ||
            city ||
            graduationYear ||
            recruitmentType ||
            employerType ||
            writtenTest ||
            deadlineWithin ||
            sort !== "updated" ||
            eligibility ||
            trust ||
            conflictOnly ? (
              <button
                className="button secondary"
                onClick={() => {
                  setSearch("");
                  setDraftSearch("");
                  setKind("");
                  setCity("");
                  setGraduationYear("");
                  setRecruitmentType("");
                  setEmployerType("");
                  setWrittenTest("");
                  setDeadlineWithin("");
                  setSort("updated");
                  setEligibility("");
                  setTrust("");
                  setConflictOnly(false);
                }}
              >
                清空筛选
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}
