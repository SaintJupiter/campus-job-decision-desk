import {
  CheckCircle2,
  Database,
  Eye,
  FilePlus2,
  Files,
  Link2,
  RefreshCw,
  ShieldAlert,
  UploadCloud,
} from "lucide-react";
import { useState } from "react";

import {
  api,
  humanDate,
  type BatchSummary,
  type FeishuPreview,
  type ImportPreview,
  type RemoteConnector,
  type RemoteSyncResponse,
  type SourceSummary,
  type SourceSyncRun,
} from "../api";
import {
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  PageHeader,
  SectionHeading,
} from "../components";
import { useRemote } from "../useRemote";
import { useRuntime } from "../runtime";

export function SourcesPage() {
  const runtime = useRuntime();
  const sources = useRemote(() => api<SourceSummary[]>("/api/sources"));
  const batches = useRemote(() => api<BatchSummary[]>("/api/sources/batches"));
  const connectors = useRemote(() =>
    api<RemoteConnector[]>("/api/sources/connectors"),
  );
  const syncRuns = useRemote(() =>
    api<SourceSyncRun[]>("/api/sources/sync-runs"),
  );
  const [result, setResult] = useState("");
  const independentGroupCount = new Set(
    (sources.data ?? []).map((source) => source.independence_group),
  ).size;

  function reload() {
    sources.reload();
    batches.reload();
    connectors.reload();
    syncRuns.reload();
  }

  return (
    <>
      <PageHeader
        eyebrow="SOURCE PROVENANCE"
        title="数据来源与批次"
        description="每次导入形成不可变批次；多个时间快照不自动视为多个独立供应商。"
      />
      {independentGroupCount < 2 && (
        <div className="notice warning">
          <ShieldAlert size={19} />
          <div>
            <strong>暂不能输出供应商质量排名</strong>
            <p>
              需要至少两个真实独立来源及人工核验样本，才能比较独有有效岗位、官方确认率和时效。
            </p>
          </div>
        </div>
      )}

      <div className="sources-layout">
        <section className="content-section">
          <SectionHeading
            title="导入新批次"
            description="支持 CSV、TSV、XLSX 与 Markdown；付费原始数据仅保存在本地。"
          />
          {runtime.read_only ? (
            <div className="notice info">
              <Eye size={18} />
              <span>
                公开演示仅展示合成数据的导入结果；请在本地模式上传自己的表格。
              </span>
            </div>
          ) : (
            <ImportForm
              sources={sources.data ?? []}
              onImported={(message) => {
                setResult(message);
                reload();
              }}
            />
          )}
          {result && (
            <div className="notice info" role="status">
              <Database size={18} />
              <span>{result}</span>
            </div>
          )}
        </section>

        <section className="content-section">
          <SectionHeading
            title="独立来源"
            description="independence group 相同的记录视为同一供应商。"
          />
          {sources.loading ? (
            <LoadingBlock />
          ) : sources.error ? (
            <ErrorBlock message={sources.error} onRetry={sources.reload} />
          ) : sources.data?.length ? (
            <div className="source-list">
              {sources.data.map((source) => (
                <article key={source.id} className="source-card">
                  <div className="source-icon">
                    <Database size={19} />
                  </div>
                  <div>
                    <h3>{source.name}</h3>
                    <p>{source.description || "未填写来源说明"}</p>
                    <div className="metadata-row">
                      <span>{sourceKindLabel(source.kind)}</span>
                      <span>独立组：{source.independence_group}</span>
                      <span>{source.batch_count} 个批次</span>
                    </div>
                  </div>
                  <strong>
                    {source.raw_record_count.toLocaleString("zh-CN")}
                    <small>原始记录</small>
                  </strong>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<Files />}
              title="还没有数据来源"
              description="使用左侧表单导入第一份岗位表，系统会保留文件哈希、行数和解析结果。"
            />
          )}
        </section>
      </div>

      <section className="content-section remote-source-section">
        <SectionHeading
          title="连接飞书多维表格"
          description="保存 table/view 身份，按官方 API 全量分页；每次成功同步形成不可变快照和新增、修改、缺失统计。"
        />
        {runtime.read_only ? (
          <div className="notice info">
            <Eye size={18} />
            <span>公开演示不读取外部飞书数据；本地工作区可配置连接。</span>
          </div>
        ) : (
          <FeishuConnectorForm
            onSynced={(message) => {
              setResult(message);
              reload();
            }}
          />
        )}
        <ConnectorList
          connectors={connectors.data ?? []}
          loading={connectors.loading}
          error={connectors.error}
          onRetry={connectors.reload}
          readOnly={runtime.read_only}
          onSynced={(message) => {
            setResult(message);
            reload();
          }}
        />
      </section>

      <section className="content-section">
        <SectionHeading
          title="远程同步记录"
          description="只有完整读到末页后才更新快照；FAILED 不会覆盖上一次成功批次。"
        />
        {syncRuns.loading ? (
          <LoadingBlock />
        ) : syncRuns.error ? (
          <ErrorBlock message={syncRuns.error} onRetry={syncRuns.reload} />
        ) : syncRuns.data?.length ? (
          <SyncRunTable runs={syncRuns.data} />
        ) : (
          <EmptyState
            title="还没有远程同步记录"
            description="先检测并连接一个飞书多维表格；每日任务也会写入这里。"
          />
        )}
      </section>

      <section className="content-section">
        <SectionHeading
          title="导入批次"
          description="失败行和重复导入应可见，成功解析不等于字段均可信。"
        />
        {batches.loading ? (
          <LoadingBlock />
        ) : batches.error ? (
          <ErrorBlock message={batches.error} onRetry={batches.reload} />
        ) : batches.data?.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>文件</th>
                  <th>格式</th>
                  <th>原始行</th>
                  <th>成功</th>
                  <th>失败</th>
                  <th>快照时间</th>
                  <th>导入时间</th>
                </tr>
              </thead>
              <tbody>
                {batches.data.map((batch) => (
                  <tr key={batch.id}>
                    <th scope="row">
                      <FilePlus2 size={15} />
                      {batch.file_name}
                      <small>{batch.id}</small>
                    </th>
                    <td>{batch.file_format.toUpperCase()}</td>
                    <td>{batch.row_count.toLocaleString("zh-CN")}</td>
                    <td>{batch.success_count.toLocaleString("zh-CN")}</td>
                    <td
                      className={
                        batch.error_count ? "text-negative" : undefined
                      }
                    >
                      {batch.error_count}
                    </td>
                    <td>{humanDate(batch.snapshot_at, true)}</td>
                    <td>{humanDate(batch.imported_at, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="还没有导入批次"
            description="成功导入文件后，批次回执会显示在这里。"
          />
        )}
      </section>
    </>
  );
}

function FeishuConnectorForm({
  onSynced,
}: {
  onSynced: (message: string) => void;
}) {
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [independenceGroup, setIndependenceGroup] = useState("");
  const [description, setDescription] = useState("");
  const [mapping, setMapping] = useState("{}");
  const [schedule, setSchedule] = useState("DAILY");
  const [preview, setPreview] = useState<FeishuPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function invalidate(action: () => void) {
    action();
    setPreview(null);
  }

  function parsedMapping() {
    const value: unknown = JSON.parse(mapping);
    if (!value || Array.isArray(value) || typeof value !== "object")
      throw new Error("字段映射必须是 JSON 对象");
    return value as Record<string, string>;
  }

  function validate(includeIdentity = false) {
    if (!sourceUrl.trim()) return "请粘贴飞书多维表格 URL";
    if (!sourceName.trim()) return "请填写来源名称";
    if (includeIdentity && !sourceId.trim()) return "请填写稳定来源 ID";
    if (includeIdentity && !independenceGroup.trim()) return "请填写独立来源组";
    try {
      parsedMapping();
    } catch (reason) {
      return reason instanceof Error ? reason.message : "字段映射不合法";
    }
    return "";
  }

  async function runPreview() {
    const validation = validate();
    if (validation) {
      setError(validation);
      return;
    }
    setPreviewing(true);
    setError("");
    try {
      setPreview(
        await api<FeishuPreview>("/api/sources/connectors/feishu/preview", {
          method: "POST",
          body: JSON.stringify({
            source_url: sourceUrl,
            source_name: sourceName,
            source_kind: "PAID_TABLE",
            mapping: parsedMapping(),
          }),
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "飞书读取检测失败");
    } finally {
      setPreviewing(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const validation = validate(true);
    if (validation) {
      setError(validation);
      return;
    }
    if (!preview) {
      setError("请先完成全量读取检测");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const response = await api<RemoteSyncResponse>(
        "/api/sources/connectors/feishu",
        {
          method: "POST",
          body: JSON.stringify({
            source_url: sourceUrl,
            source_id: sourceId,
            source_name: sourceName,
            source_kind: "PAID_TABLE",
            independence_group: independenceGroup,
            description,
            mapping: parsedMapping(),
            schedule,
          }),
        },
      );
      onSynced(syncMessage(response));
      setPreview(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存连接失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="stack-form remote-source-form" onSubmit={submit}>
      <label>
        <span>飞书多维表格 URL</span>
        <input
          type="url"
          required
          value={sourceUrl}
          onChange={(event) =>
            invalidate(() => setSourceUrl(event.target.value))
          }
          placeholder="https://…feishu.cn/base/…?table=tbl…&view=vew…"
        />
      </label>
      <div className="form-grid two">
        <label>
          <span>来源名称</span>
          <input
            required
            value={sourceName}
            onChange={(event) =>
              invalidate(() => setSourceName(event.target.value))
            }
            placeholder="例如：供应商 A 每日表"
          />
        </label>
        <label>
          <span>稳定来源 ID</span>
          <input
            required
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
            placeholder="vendor-a-feishu"
          />
        </label>
      </div>
      <div className="form-grid two">
        <label>
          <span>独立来源组</span>
          <input
            required
            value={independenceGroup}
            onChange={(event) => setIndependenceGroup(event.target.value)}
            placeholder="vendor-a"
          />
        </label>
        <label>
          <span>同步频率</span>
          <select
            value={schedule}
            onChange={(event) => setSchedule(event.target.value)}
          >
            <option value="DAILY">每日任务</option>
            <option value="MANUAL">仅手动</option>
          </select>
        </label>
      </div>
      <label>
        <span>说明</span>
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="授权范围、购买日期或使用说明"
        />
      </label>
      <details className="mapping-details">
        <summary>自定义字段映射</summary>
        <textarea
          value={mapping}
          onChange={(event) => invalidate(() => setMapping(event.target.value))}
          spellCheck={false}
        />
      </details>
      <p className="form-help">
        普通分享页若跳转登录，需在本地环境配置飞书 access
        token；凭证不会写入数据库或前端。
      </p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="import-actions">
        <button
          type="button"
          className="button secondary"
          disabled={previewing || saving}
          onClick={runPreview}
        >
          <Eye size={16} />
          {previewing ? "正在逐页读取…" : "检测并全量预览"}
        </button>
        <button className="button primary" disabled={saving || !preview}>
          <Link2 size={16} />
          {saving ? "正在保存并同步…" : "保存连接并生成首个快照"}
        </button>
      </div>
      {preview && (
        <div className="remote-preview-meta" role="status">
          <strong>
            已读完 {preview.page_count} 页、{preview.preview.row_count} 行、
            {preview.field_count} 个字段
          </strong>
          <span>
            table {preview.table_id} · view {preview.view_id || "默认视图"} ·
            {humanDate(preview.fetched_at, true)}
          </span>
          <ImportPreviewPanel preview={preview.preview} />
        </div>
      )}
    </form>
  );
}

function ConnectorList({
  connectors,
  loading,
  error,
  onRetry,
  readOnly,
  onSynced,
}: {
  connectors: RemoteConnector[];
  loading: boolean;
  error: string;
  onRetry: () => void;
  readOnly: boolean;
  onSynced: (message: string) => void;
}) {
  const [syncing, setSyncing] = useState("");
  const [syncError, setSyncError] = useState("");

  async function sync(sourceId: string) {
    setSyncing(sourceId);
    setSyncError("");
    try {
      const response = await api<RemoteSyncResponse>(
        `/api/sources/${sourceId}/sync`,
        { method: "POST" },
      );
      onSynced(syncMessage(response));
    } catch (reason) {
      setSyncError(reason instanceof Error ? reason.message : "同步失败");
    } finally {
      setSyncing("");
    }
  }

  if (loading) return <LoadingBlock />;
  if (error) return <ErrorBlock message={error} onRetry={onRetry} />;
  if (!connectors.length) return null;
  return (
    <div className="connector-list">
      {syncError && (
        <p className="form-error" role="alert">
          {syncError}
        </p>
      )}
      {connectors.map((connector) => (
        <article className="connector-card" key={connector.source_id}>
          <div>
            <span
              className={`sync-status ${connector.last_status.toLowerCase()}`}
            >
              {syncStatusLabel(connector.last_status)}
            </span>
            <h3>{connector.source_name}</h3>
            <p>
              {connector.table_id} · {connector.view_id || "默认视图"} ·
              {connector.schedule === "DAILY" ? "每日" : "手动"}
            </p>
            <small>
              最近同步 {humanDate(connector.last_sync_at, true)}
              {connector.last_error ? ` · ${connector.last_error}` : ""}
            </small>
          </div>
          {!readOnly && (
            <button
              className="button secondary small"
              disabled={syncing === connector.source_id}
              onClick={() => sync(connector.source_id)}
            >
              <RefreshCw size={14} />
              {syncing === connector.source_id ? "同步中…" : "立即同步"}
            </button>
          )}
        </article>
      ))}
    </div>
  );
}

function SyncRunTable({ runs }: { runs: SourceSyncRun[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>来源 / 时间</th>
            <th>状态</th>
            <th>全量</th>
            <th>新增</th>
            <th>修改</th>
            <th>缺失</th>
            <th>未变</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <th scope="row">
                {run.source_id}
                <small>{humanDate(run.started_at, true)}</small>
              </th>
              <td>
                <span className={`sync-status ${run.status.toLowerCase()}`}>
                  {syncStatusLabel(run.status)}
                </span>
                {run.error && <small>{run.error}</small>}
              </td>
              <td>{run.row_count.toLocaleString("zh-CN")}</td>
              <td>+{run.added_count}</td>
              <td>~{run.modified_count}</td>
              <td className={run.missing_count ? "text-negative" : undefined}>
                -{run.missing_count}
              </td>
              <td>{run.unchanged_count.toLocaleString("zh-CN")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function syncMessage(response: RemoteSyncResponse) {
  return `飞书全量同步${response.status === "NO_CHANGE" ? "完成（无变化）" : "完成"}：${response.row_count} 行，新增 ${response.added_count}、修改 ${response.modified_count}、缺失 ${response.missing_count}。`;
}

function syncStatusLabel(value: string) {
  return (
    (
      {
        NEVER: "尚未同步",
        RUNNING: "同步中",
        SUCCESS: "同步成功",
        NO_CHANGE: "无变化",
        FAILED: "同步失败",
      } as Record<string, string>
    )[value] ?? value
  );
}

function ImportForm({
  sources,
  onImported,
}: {
  sources: SourceSummary[];
  onImported: (message: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [pastedTable, setPastedTable] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [independenceGroup, setIndependenceGroup] = useState("");
  const [sourceKind, setSourceKind] = useState("PAID_TABLE");
  const [description, setDescription] = useState("");
  const [mapping, setMapping] = useState("{}");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const existingSource = sources.find((item) => item.id === sourceId);

  function chooseExisting(id: string) {
    setSourceId(id);
    setPreview(null);
    const source = sources.find((item) => item.id === id);
    if (source) {
      setSourceName(source.name);
      setIndependenceGroup(source.independence_group);
      setSourceKind(source.kind);
      setDescription(source.description);
    }
  }

  function updatePreviewInput(action: () => void) {
    action();
    setPreview(null);
  }

  function usePastedTable() {
    if (!pastedTable.trim()) {
      setError("请先从飞书表格复制全表并粘贴到文本框");
      return;
    }
    const firstLine = pastedTable.split(/\r?\n/, 1)[0] ?? "";
    if (!firstLine.includes("\t")) {
      setError("粘贴内容不像表格：首行没有制表符，请在飞书表格内全选后复制");
      return;
    }
    const snapshot = new File(
      [pastedTable],
      `feishu-public-${new Date().toISOString().slice(0, 10)}.tsv`,
      { type: "text/tab-separated-values;charset=utf-8" },
    );
    updatePreviewInput(() => setFile(snapshot));
    setError("");
  }

  function validate() {
    if (!file) return "请选择要导入的文件";
    if (!sourceName.trim()) return "请填写来源名称";
    try {
      const parsed = JSON.parse(mapping);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object")
        return "字段映射必须是合法 JSON 对象";
    } catch {
      return "字段映射必须是合法 JSON 对象";
    }
    return "";
  }

  function previewForm() {
    const form = new FormData();
    form.set("file", file as File);
    form.set("source_name", sourceName);
    form.set("source_kind", sourceKind);
    form.set("mapping_json", mapping);
    return form;
  }

  async function runPreview() {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setPreviewing(true);
    setError("");
    try {
      setPreview(
        await api<ImportPreview>("/api/sources/preview", {
          method: "POST",
          body: previewForm(),
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "预览失败");
    } finally {
      setPreviewing(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    if (!preview) {
      setError("请先完成导入预览并检查分类结果");
      return;
    }
    if (!file) {
      setError("请选择要导入的文件");
      return;
    }
    if (!independenceGroup.trim()) {
      setError("请填写独立来源组");
      return;
    }
    setSaving(true);
    setError("");
    const form = new FormData();
    form.set("file", file);
    form.set("source_id", sourceId || `source-${Date.now()}`);
    form.set("source_name", sourceName);
    form.set("independence_group", independenceGroup);
    form.set("source_kind", sourceKind);
    form.set("description", description);
    form.set("mapping_json", mapping);
    try {
      const response = await api<{
        status: string;
        row_count: number;
        success_count: number;
        error_count: number;
        materialized_count: number;
      }>("/api/sources/import", { method: "POST", body: form });
      onImported(
        `导入完成：${response.success_count}/${response.row_count} 行成功，${response.error_count} 行失败，生成 ${response.materialized_count} 条机会记录。`,
      );
      setFile(null);
      setPreview(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="stack-form import-form" onSubmit={submit}>
      {sources.length > 0 && (
        <label>
          <span>沿用已有来源（可选）</span>
          <select
            value={sourceId}
            onChange={(event) => chooseExisting(event.target.value)}
          >
            <option value="">创建新来源</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="file-drop">
        <UploadCloud size={24} />
        <span>{file ? file.name : "选择岗位表文件"}</span>
        <small>CSV / TSV / XLSX / Markdown</small>
        <input
          type="file"
          accept=".csv,.tsv,.xlsx,.xlsm,.md,.markdown,.txt"
          onChange={(event) =>
            updatePreviewInput(() => setFile(event.target.files?.[0] ?? null))
          }
        />
      </label>
      <details className="paste-import-details">
        <summary>公开飞书分享页：复制全表后粘贴</summary>
        <p>
          适用于无需登录但没有 API
          凭证的分享页：在飞书表格内全选、复制，再粘贴到这里；系统仍会先做行数、表头与分类预览。
        </p>
        <textarea
          aria-label="粘贴岗位表文本"
          value={pastedTable}
          onChange={(event) => {
            setPastedTable(event.target.value);
            setPreview(null);
          }}
          placeholder="公司名称[TAB]更新日期[TAB]企业类型…"
          spellCheck={false}
        />
        <div className="paste-import-actions">
          <small>
            当前粘贴 {pastedTable.length.toLocaleString("zh-CN")} 字符
          </small>
          <button
            type="button"
            className="button secondary small"
            onClick={usePastedTable}
          >
            使用粘贴内容
          </button>
        </div>
      </details>
      <div className="form-grid two">
        <label>
          <span>来源名称</span>
          <input
            required
            disabled={Boolean(existingSource)}
            value={sourceName}
            onChange={(event) =>
              updatePreviewInput(() => setSourceName(event.target.value))
            }
            placeholder="例如：供应商 A"
          />
        </label>
        <label>
          <span>独立来源组</span>
          <input
            required
            disabled={Boolean(existingSource)}
            value={independenceGroup}
            onChange={(event) => setIndependenceGroup(event.target.value)}
            placeholder="vendor-a"
          />
        </label>
      </div>
      <div className="form-grid two">
        <label>
          <span>来源类型</span>
          <select
            disabled={Boolean(existingSource)}
            value={sourceKind}
            onChange={(event) =>
              updatePreviewInput(() => setSourceKind(event.target.value))
            }
          >
            <option value="PAID_TABLE">付费表格</option>
            <option value="PUBLIC_AGGREGATOR">公开聚合</option>
            <option value="OFFICIAL">官方文件（仍需确认域名）</option>
          </select>
        </label>
        <label>
          <span>说明</span>
          <input
            disabled={Boolean(existingSource)}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="购买日期、用途或范围"
          />
        </label>
      </div>
      {existingSource && (
        <p className="form-help">
          已沿用“{existingSource.name}
          ”的固定来源身份；名称、类型与独立来源组不可在导入时改写。
        </p>
      )}
      <details className="mapping-details">
        <summary>自定义字段映射</summary>
        <textarea
          value={mapping}
          onChange={(event) =>
            updatePreviewInput(() => setMapping(event.target.value))
          }
          spellCheck={false}
        />
        <p>映射修改后需重新预览；预览不会写入数据库。</p>
      </details>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="import-actions">
        <button
          type="button"
          className="button secondary"
          disabled={previewing || saving}
          onClick={runPreview}
        >
          <Eye size={16} />
          {previewing ? "正在解析…" : "先预览解析"}
        </button>
        <button className="button primary" disabled={saving || !preview}>
          <UploadCloud size={16} />
          {saving ? "正在导入…" : "确认导入并生成批次"}
        </button>
      </div>
      {preview && <ImportPreviewPanel preview={preview} />}
    </form>
  );
}

function ImportPreviewPanel({ preview }: { preview: ImportPreview }) {
  return (
    <section className="import-preview" aria-label="导入预览">
      <div className="preview-heading">
        <div>
          <CheckCircle2 size={17} />
          <strong>预览完成，可以确认导入</strong>
        </div>
        <small>映射规则 {preview.mapping_version}</small>
      </div>
      <div className="preview-counts">
        <span>
          <strong>{preview.row_count}</strong>原始行
        </span>
        <span>
          <strong>{preview.kind_counts.POSTING}</strong>具体岗位
        </span>
        <span>
          <strong>{preview.kind_counts.CAMPAIGN}</strong>招聘项目
        </span>
        <span>
          <strong>{preview.kind_counts.NON_JOB}</strong>非岗位行
        </span>
        <span className={preview.error_count ? "text-negative" : undefined}>
          <strong>{preview.error_count}</strong>失败行
        </span>
      </div>
      <p className="preview-meta">
        识别表头：{preview.header.join("、") || "未识别"} · 文件指纹{" "}
        {preview.file_hash.slice(0, 12)}…
      </p>
      {preview.sample_rows.length > 0 && (
        <div className="table-wrap">
          <table className="data-table preview-table">
            <thead>
              <tr>
                <th>行</th>
                <th>公司 / 岗位</th>
                <th>分类</th>
                <th>城市</th>
                <th>分类依据</th>
              </tr>
            </thead>
            <tbody>
              {preview.sample_rows.map((row) => (
                <tr key={row.row_number}>
                  <td>{row.row_number}</td>
                  <th scope="row">
                    {row.canonical.company || "公司为空"}
                    <small>{row.canonical.title || "岗位为空"}</small>
                  </th>
                  <td>
                    <span
                      className={`preview-kind ${row.kind.needs_review ? "needs-review" : ""}`}
                    >
                      {row.kind.kind === "POSTING"
                        ? "具体岗位"
                        : row.kind.kind === "CAMPAIGN"
                          ? "招聘项目"
                          : "非岗位行"}
                      {row.kind.needs_review ? " · 待复核" : ""}
                    </span>
                  </td>
                  <td>{row.canonical.cities?.join("、") || "—"}</td>
                  <td>
                    {row.kind.reasons.join("；") ||
                      row.errors.join("；") ||
                      "未返回理由"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {preview.rejected_rows.length > 0 && (
        <p className="preview-warning">
          另有 {preview.rejected_rows.length}{" "}
          条拒绝记录；确认导入后仍会保留失败回执。
        </p>
      )}
    </section>
  );
}

function sourceKindLabel(value: string) {
  return (
    (
      {
        PAID_TABLE: "付费表格",
        PUBLIC_AGGREGATOR: "公开聚合",
        OFFICIAL: "官方来源",
        SYNTHETIC: "合成演示",
      } as Record<string, string>
    )[value] ?? value
  );
}
