import type {
  BatchSummary,
  DashboardSummary,
  DuplicateCandidate,
  EvaluationSummary,
  Opportunity,
  OpportunityDetail,
  PaginatedOpportunities,
  Profile,
  RemoteConnector,
  RuntimeMeta,
  ShortlistEntry,
  SourceSummary,
  SourceSyncRun,
} from "./api";

interface StaticDemoBundle {
  schema_version: string;
  generated_at: string;
  meta: RuntimeMeta;
  dashboard: DashboardSummary;
  opportunities: Opportunity[];
  ready_queue: Opportunity[];
  verify_first_queue: Opportunity[];
  details: Record<string, OpportunityDetail>;
  profile: Profile;
  shortlist: ShortlistEntry[];
  sources: SourceSummary[];
  batches: BatchSummary[];
  connectors: RemoteConnector[];
  sync_runs: SourceSyncRun[];
  duplicates: DuplicateCandidate[];
  evaluation: EvaluationSummary;
}

let bundlePromise: Promise<StaticDemoBundle> | null = null;

function loadBundle() {
  if (!bundlePromise) {
    bundlePromise = fetch(`${import.meta.env.BASE_URL}demo-data.json`).then(
      async (response) => {
        if (!response.ok) {
          throw new Error(`静态演示数据读取失败（${response.status}）`);
        }
        return (await response.json()) as StaticDemoBundle;
      },
    );
  }
  return bundlePromise;
}

export async function staticDemoApi<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    throw new Error("在线演示使用只读合成数据；完整操作请在本地工作区运行。");
  }

  const bundle = await loadBundle();
  const url = new URL(path, "https://static-demo.local");
  const endpoint = url.pathname;
  let result: unknown;

  if (endpoint === "/api/meta") result = bundle.meta;
  else if (endpoint === "/api/workspace/dashboard") result = bundle.dashboard;
  else if (endpoint === "/api/workspace/profile") result = bundle.profile;
  else if (endpoint === "/api/workspace/shortlist") result = bundle.shortlist;
  else if (endpoint === "/api/evaluation/summary") result = bundle.evaluation;
  else if (endpoint === "/api/sources") result = bundle.sources;
  else if (endpoint === "/api/sources/batches") result = bundle.batches;
  else if (endpoint === "/api/sources/connectors") result = bundle.connectors;
  else if (endpoint === "/api/sources/sync-runs") result = bundle.sync_runs;
  else if (endpoint === "/api/opportunities/review/duplicates") {
    const limit = numberParam(url, "limit", 50);
    result = bundle.duplicates.slice(0, limit);
  } else if (endpoint === "/api/workspace/decision-queue") {
    const queue = url.searchParams.get("queue");
    const items =
      queue === "ready" ? bundle.ready_queue : bundle.verify_first_queue;
    result = paginate(items, url);
  } else if (endpoint === "/api/opportunities") {
    result = filterOpportunities(bundle, url);
  } else {
    const detailMatch = endpoint.match(/^\/api\/opportunities\/([^/]+)$/u);
    const detailId = detailMatch?.[1];
    if (detailId) result = bundle.details[decodeURIComponent(detailId)];
  }

  if (result === undefined) throw new Error("静态演示中没有这项数据。");
  return structuredClone(result) as T;
}

function filterOpportunities(bundle: StaticDemoBundle, url: URL) {
  let items = [...bundle.opportunities];
  const search = normalizedParam(url, "search");
  const kind = normalizedParam(url, "kind");
  const city = normalizedParam(url, "city");
  const graduationYear = normalizedParam(url, "graduation_year");
  const recruitmentType = normalizedParam(url, "recruitment_type");
  const employerType = normalizedParam(url, "employer_type");
  const writtenTest = normalizedParam(url, "written_test");
  const eligibility = normalizedParam(url, "eligibility");
  const trust = normalizedParam(url, "trust");
  const reviewStatus = normalizedParam(url, "review_status");
  const manualDecision = normalizedParam(url, "manual_decision");
  const verification = normalizedParam(url, "verification");

  if (search) {
    items = items.filter((item) =>
      [item.title, item.source_title, item.company]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase().includes(search)),
    );
  }
  if (kind) items = items.filter((item) => item.kind === kind);
  if (city) items = items.filter((item) => includesToken(item.cities, city));
  if (graduationYear)
    items = items.filter((item) =>
      includesToken(item.graduation_years, graduationYear),
    );
  if (recruitmentType)
    items = items.filter((item) =>
      includesText(item.recruitment_type, recruitmentType),
    );
  if (employerType)
    items = items.filter((item) =>
      includesText(item.employer_type, employerType),
    );
  if (writtenTest)
    items = items.filter((item) =>
      includesText(item.written_test, writtenTest),
    );
  if (eligibility)
    items = items.filter(
      (item) => item.decision_current && item.eligibility === eligibility,
    );
  if (trust)
    items = items.filter(
      (item) => item.decision_current && item.trust === trust,
    );
  if (reviewStatus)
    items = items.filter((item) => item.review_status === reviewStatus);
  if (manualDecision)
    items = items.filter((item) => item.manual_decision === manualDecision);
  if (verification)
    items = items.filter((item) => item.verification === verification);
  if (url.searchParams.get("conflict_only") === "true")
    items = items.filter((item) => item.conflict_count > 0);

  const deadlineWithin = numberParam(url, "deadline_within_days", 0);
  if (deadlineWithin > 0) {
    const start = new Date(bundle.generated_at);
    const end = new Date(start);
    end.setUTCDate(end.getUTCDate() + deadlineWithin);
    items = items.filter((item) => {
      const deadline = parseDate(item.deadline);
      return deadline !== null && deadline >= start && deadline <= end;
    });
  }

  if (url.searchParams.get("sort") === "deadline") {
    items.sort(
      (left, right) => dateRank(left.deadline) - dateRank(right.deadline),
    );
  } else {
    items.sort((left, right) =>
      right.updated_at.localeCompare(left.updated_at),
    );
  }
  return paginate(items, url);
}

function paginate(items: Opportunity[], url: URL): PaginatedOpportunities {
  const page = numberParam(url, "page", 1);
  const pageSize = numberParam(url, "page_size", 30);
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    total: items.length,
    page,
    page_size: pageSize,
  };
}

function normalizedParam(url: URL, key: string) {
  return (url.searchParams.get(key) ?? "").trim().toLocaleLowerCase();
}

function numberParam(url: URL, key: string, fallback: number) {
  const value = Number(url.searchParams.get(key));
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

function includesToken(values: string[], token: string) {
  return values.some((value) => value.toLocaleLowerCase().includes(token));
}

function includesText(value: string | undefined, token: string) {
  return (value ?? "").toLocaleLowerCase().includes(token);
}

function parseDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(value)) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dateRank(value: string) {
  return parseDate(value)?.getTime() ?? Number.MAX_SAFE_INTEGER;
}
