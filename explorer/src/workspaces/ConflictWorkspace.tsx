import { useEffect, useState } from 'react';

type Claim = { quote: string; entity: string; property: string; value: string; conditions: string; valid_time: string; source: { document_title: string; chunk_id: string; document_id: string } };
type Finding = { pair_id: string; kind: string; reason: string; left: Claim; right: Claim };
type Status = {
  knowledge_base: { name: string }; captured_at: string;
  coverage: { documents: number; chunks: number; issues: unknown[] };
  audit: { status: string; chunks_processed?: number; chunks_total?: number; claims?: number; pairs_total?: number; pairs_checked?: number; model?: string; limitations?: string[] };
  conflict_count: number; uncertain_count: number; errors: { message: string; stage: string }[];
};
const labels: Record<string, string> = { checking_model: '正在检查模型连通性', extracting: '正在抽取事实', comparing: '正在核对候选冲突', completed: '本轮扫描完成', partial: '部分完成，请检查失败项', failed: '任务失败', not_started: '尚未启动' };

async function getJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `请求失败 (${response.status})`);
  }
  return response.json();
}

export function ConflictWorkspace() {
  const [status, setStatus] = useState<Status>();
  const [items, setItems] = useState<Finding[]>([]);
  const [kind, setKind] = useState('conflicts');
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState('');
  const [source, setSource] = useState<{ content: string; document_title: string }>();
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const next = await getJson<Status>('/api/conflicts/weknora');
        if (!active) return;
        setStatus(next);
        if (next.audit.status !== 'not_started') {
          const rows = await getJson<{ items: Finding[]; total: number }>(`/api/conflicts/weknora/findings?kind=${kind}&offset=${offset}`);
          if (active) { setItems(rows.items); setTotal(rows.total); }
        }
        if (active) setError('');
      } catch (e) { if (active) setError(String(e)); }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => { active = false; clearInterval(timer); };
  }, [kind, offset]);

  async function start() {
    setStarting(true);
    try { await getJson('/api/conflicts/weknora/audit', { method: 'POST' }); setError(''); }
    catch (e) { setError(String(e)); }
    finally { setStarting(false); }
  }

  async function viewSource(chunk: string) {
    try { setSource(await getJson(`/api/conflicts/weknora/source/${encodeURIComponent(chunk)}`)); }
    catch (e) { setError(String(e)); }
  }

  const running = ['checking_model', 'extracting', 'comparing'].includes(status?.audit.status || '');
  const card = { background: 'var(--ws-surface)', border: '1px solid var(--ws-border)', borderRadius: 12, padding: 20 };
  return <div className="ws-page" style={{ overflow: 'auto', padding: 24, gap: 20 }}>
    <div><h2 style={{ marginTop: 0 }}>知识库文档冲突检测</h2><p>读取 WeKnora 原始解析分块，比较同一主体、属性、适用条件与有效时间下的事实。</p></div>
    {error && <div role="alert" style={{ color: 'var(--ws-red)' }}>{error}</div>}
    {status && <>
      <div style={card}>
        <h3>{status.knowledge_base.name}</h3>
        <p>{status.coverage.documents} 份文档 · {status.coverage.chunks} 个分块 · {status.coverage.issues.length} 项来源覆盖问题</p>
        <p>快照时间：{new Date(status.captured_at).toLocaleString()}</p>
        <strong aria-live="polite">{labels[status.audit.status] || status.audit.status}</strong>
        <p>已处理分块 {status.audit.chunks_processed ?? 0}/{status.audit.chunks_total ?? status.coverage.chunks} · 已抽取事实 {status.audit.claims ?? 0} · 已核对候选对 {status.audit.pairs_checked ?? 0}/{status.audit.pairs_total ?? 0}</p>
        <progress value={status.audit.chunks_processed ?? 0} max={status.coverage.chunks} style={{ width: '100%' }} />
        <p>模型：{status.audit.model || 'Codex CLI'} · 冲突 {status.conflict_count} · 待复核 {status.uncertain_count} · 失败 {status.errors.length}</p>
        <button className="ws-btn" disabled={running || starting} onClick={() => void start()}>{running ? '检测进行中' : starting ? '正在启动…' : '运行 / 重试检测'}</button>
        <p style={{ color: 'var(--ws-text-muted)', fontSize: 13 }}>按当前冻结快照运行；来源未被修改。全量读取不代表保证发现所有冲突，结果需人工复核。</p>
        <details><summary>检测范围与限制</summary>{status.audit.limitations?.map(line => <p key={line}>{line}</p>)}</details>
        {status.errors.length > 0 && <details><summary>失败项（{status.errors.length}）</summary>{status.errors.map((e, i) => <p key={i}>{e.stage}：{e.message}</p>)}</details>}
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        <button className="ws-btn" aria-pressed={kind === 'conflicts'} onClick={() => { setKind('conflicts'); setOffset(0); }}>冲突 ({status.conflict_count})</button>
        <button className="ws-btn" aria-pressed={kind === 'uncertain'} onClick={() => { setKind('uncertain'); setOffset(0); }}>待复核 ({status.uncertain_count})</button>
      </div>
      {items.length === 0 && <p>{running ? '正在分析，结果会自动刷新。' : '本页暂无结果；请同时检查覆盖率、失败项及待复核项。'}</p>}
      {items.map(item => <article key={item.pair_id} style={card}>
        <h3>{item.kind} · {item.left.entity} / {item.left.property}</h3>
        <p>{item.reason}</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20 }}>
          {[item.left, item.right].map((claim, i) => <div key={i}>
            <strong>{claim.source.document_title}</strong>
            <blockquote style={{ whiteSpace: 'pre-wrap', margin: '12px 0', borderLeft: '3px solid var(--ws-accent)', paddingLeft: 12 }}>{claim.quote}</blockquote>
            <p>适用条件：{claim.conditions || '未明确'} · 时间：{claim.valid_time || '未明确'}</p>
            <button className="ws-btn" onClick={() => void viewSource(claim.source.chunk_id)}>查看原文分块</button>
          </div>)}
        </div>
      </article>)}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <button className="ws-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset-30))}>上一页</button>
        <span>{total ? offset+1 : 0}–{Math.min(offset+30, total)} / {total}</span>
        <button className="ws-btn" disabled={offset+30 >= total} onClick={() => setOffset(offset+30)}>下一页</button>
      </div>
    </>}
    {source && <div role="dialog" aria-label="原文分块" style={{ ...card, position: 'fixed', inset: '15% 10%', overflow: 'auto', background: 'var(--ws-bg)', zIndex: 100 }}>
      <button className="ws-btn" onClick={() => setSource(undefined)}>关闭</button><h3>{source.document_title}</h3><pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>{source.content}</pre>
    </div>}
  </div>;
}
