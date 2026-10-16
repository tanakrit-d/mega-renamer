import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowRightIcon, CheckIcon, CopyIcon, FileTextIcon, Link2Icon, MixerHorizontalIcon, ReloadIcon, ExternalLinkIcon, LockClosedIcon, LightningBoltIcon, TrashIcon } from '@radix-ui/react-icons';
import { Button } from './components/ui/button';
import { RulesEditor } from './components/rules-editor';
import { ThemePicker } from './components/theme-picker';
import './style.css';

const terminal = ['complete', 'failed', 'trashed', 'deleted'];
function bytes(value) {
  if (value == null) return '—';
  if (!value) return '0 B';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** power).toFixed(power ? 2 : 0)} ${units[power]}`;
}

function ConfirmAction({ action, busy, onCancel, onConfirm }) {
  const ref = useRef(null);
  useEffect(() => { ref.current.showModal(); }, []);
  const fullEmpty = action.kind !== 'trash';
  const history = ['remove-history', 'clear-history'].includes(action.kind);
  return <dialog ref={ref} className="confirm-dialog" aria-labelledby="confirm-title" onCancel={e => { e.preventDefault(); if (!busy) onCancel(); }}>
    <h2 id="confirm-title">{history ? action.kind === 'clear-history' ? 'Clear finished import history?' : 'Remove this import from history?' : action.kind === 'trash' ? 'Move this import to trash?' : action.kind === 'trash-empty' ? 'Trash this import and empty the trash?' : 'Empty the account trash?'}</h2>
    <p>{history ? `${action.kind === 'clear-history' ? 'All completed, failed, trashed, and deleted import records, including older entries not shown here, will be removed. Queued imports are kept.' : 'This import record will be removed.'} Saved logs, filenames, and links will be removed from this workspace. Your cloud files stay in MEGA. Removing history cannot be undone.` : fullEmpty ? 'This permanently deletes everything currently in the MEGA account rubbish bin, including unrelated files and other imports. This cannot be undone.' : 'The entire import folder will move to your MEGA rubbish bin. It can be restored there, and it continues to use storage until the trash is emptied.'}</p>
    <div className="dialog-actions"><Button variant="outline" disabled={busy} onClick={onCancel}>Cancel</Button><Button className="danger" disabled={busy} onClick={onConfirm}><TrashIcon />{busy ? 'Working…' : history ? action.kind === 'clear-history' ? 'Clear history' : 'Remove record' : fullEmpty ? 'Permanently empty trash' : 'Move to trash'}</Button></div>
  </dialog>;
}

function JobDiagnostics({ job }) {
  return <section className="job-diagnostics" aria-label="Import diagnostics">
    {job.error && job.status === 'failed' && <div role="alert" className="error"><strong>Import failed</strong><p>{job.error}</p><small>Any imported files are retained. Review the destination before starting another import.</small></div>}
    {job.status === 'trashed' && <p className="import-state">This import is in the MEGA rubbish bin. It still uses cloud storage.</p>}
    {job.status === 'deleted' && <p className="import-state">This import has been permanently deleted. Its activity log is retained.</p>}
    {job.capacity && <p className="capacity-summary">Source size: {bytes(job.capacity.sourceBytes)} · Required with report reserve: {bytes(job.capacity.requiredBytes)} · Available at check: {bytes(job.capacity.availableBytes)}</p>}
    {job.destination && <div className="destination"><span>{['trashed', 'deleted'].includes(job.status) ? 'Original MEGA destination' : 'MEGA destination'}</span><code>{job.destination}</code></div>}
    <details className="job-log" key={job.id} open>
      <summary>Activity log <span>{job.logs?.length || 0} entries</span></summary>
      <div className="log-entries" tabIndex={0} aria-label="Scrollable activity log">
        {job.logs?.length ? job.logs.map((entry, i) => <div className={'log-entry ' + entry.level} key={i}>
          <time dateTime={entry.time} title={entry.time}>{new Date(entry.time).toLocaleTimeString()}</time>
          <span className="log-level">{entry.level}</span><span>{entry.message}</span>
        </div>) : <p>No activity log was recorded for this older import. Any saved error is shown above.</p>}
      </div>
      <p className="log-hint">Updates automatically. The latest 500 entries are kept; links and credentials are redacted.</p>
    </details>
  </section>;
}

function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const sessionGeneration = useRef(0);
  const [draft, setDraft] = useState('');
  const [url, setUrl] = useState('');
  const [jobs, setJobs] = useState([]);
  const [account, setAccount] = useState(false);
  const [active, setActive] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [storage, setStorage] = useState(null);
  const [storageError, setStorageError] = useState('');
  const [capacityCheck, setCapacityCheck] = useState(null);
  const [confirmation, setConfirmation] = useState(null);
  const [notice, setNotice] = useState('');
  function disconnectState() {
    sessionGeneration.current += 1;
    setAuthenticated(false); setJobs([]); setAccount(false); setStorage(null);
    setStorageError(''); setActive(null); setCapacityCheck(null); setConfirmation(null);
  }
  async function api(path, options = {}, key = null) {
    const headers = {'Content-Type': 'application/json'};
    if (key) headers.Authorization = 'Bearer ' + key;
    const response = await fetch('/api/' + path, { ...options, headers, credentials: 'same-origin' });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 401) disconnectState();
      const error = new Error(result.error || 'Request failed');
      error.status = response.status;
      throw error;
    }
    return result;
  }
  async function refresh(key = null) {
    const generation = sessionGeneration.current;
    const [list, status] = await Promise.all([api('jobs', {}, key), api('account', {}, key)]);
    if (generation !== sessionGeneration.current) return;
    setJobs(list); setAccount(status.connected);
    if (status.connected) {
      try { const value = await api('storage', {}, key); if (generation === sessionGeneration.current) {setStorage(value); setStorageError('');} }
      catch (e) { if (generation === sessionGeneration.current) {setStorage(null); setStorageError(e.message);} }
    } else { setStorage(null); setStorageError(''); }
  }
  useEffect(() => {
    let live = true;
    api('session').then(async () => {if (live) {setAuthenticated(true); await refresh();}})
      .catch(e => {if (live && e.status !== 401) setError(e.message);})
      .finally(() => {if (live) setRestoring(false);});
    return () => {live = false;};
  }, []);
  useEffect(() => {
    if (!authenticated) return;
    const interval = setInterval(() => refresh().catch(e => setError(e.message)), 2500);
    return () => clearInterval(interval);
  }, [authenticated]);
  async function connect(e) {
    e.preventDefault(); setBusy(true); setError('');
    try { await api('session', {method: 'POST'}, draft); setDraft(''); setAuthenticated(true); await refresh(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function signOut() {
    setBusy(true); setError('');
    try {await api('session', {method: 'DELETE'}); disconnectState(); setNotice('Workspace disconnected. Your MEGA account remains signed in.');}
    catch(e) {setError(e.message);}
    finally {setBusy(false);}
  }
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      const result = await api('import-check', { method: 'POST', body: JSON.stringify({ url }) });
      setCapacityCheck(result);
      if (!result.fits) return;
      const job = await api('jobs', { method: 'POST', body: JSON.stringify({ url }) }); setActive(job.id); setUrl(''); setCapacityCheck(null); await refresh();
    }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function inspectLink() {
    setBusy(true); setError(''); setCapacityCheck(null);
    try { setCapacityCheck(await api('import-check', { method: 'POST', body: JSON.stringify({ url }) })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function manage() {
    const action = confirmation;
    setBusy(true); setError(''); setNotice('');
    try {
      if (['remove-history', 'clear-history'].includes(action.kind)) {
        const path = action.kind === 'clear-history' ? 'jobs' : `jobs/${action.id}`;
        const result = await api(path, {method: 'DELETE'});
        setActive(null);
        setNotice(`${result.removedRecords} import record${result.removedRecords === 1 ? '' : 's'} removed from history. Cloud files remain in MEGA.`);
      } else {
        const path = action.kind === 'empty' ? 'trash/empty' : `jobs/${action.id}/${action.kind}`;
        await api(path, { method: 'POST', body: JSON.stringify(action.kind === 'trash' ? {} : { confirm: 'EMPTY_ACCOUNT_TRASH' }) });
        setNotice(action.kind === 'trash' ? 'Import moved to trash.' : 'Account trash emptied. Storage totals may take a moment to update.');
      }
    } catch (e) { setError(e.message); }
    finally { setConfirmation(null); await refresh().catch(e => setError(e.message)); setBusy(false); }
  }
  const selected = jobs.find(j => j.id === active) || jobs[0];
  const completed = jobs.filter(j => j.status === 'complete');
  const renamed = completed.reduce((n, j) => n + j.files.filter(f => f.original !== f.renamed).length, 0);
  async function copy() {
    try { await navigator.clipboard.writeText(selected.files.filter(f => f.url).map(f => f.url).concat(selected.manifestUrl || []).join('\n')); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { setError('Clipboard unavailable. Copy the links individually.'); }
  }
  return <div className="shell">
    <aside><a className="brand" href="/"><span className="brand-mark">m<span>↗</span></span>mega<span className="brand-light">renamer</span></a><div className="workspace-label">WORKSPACE</div><a className="nav active" href="#import"><Link2Icon />Import & rename</a><a className="nav" href="#rules"><MixerHorizontalIcon />Naming rules</a><a className="nav" href="#activity"><ReloadIcon />Recent imports <span className="count">{jobs.length}</span></a><div className="aside-bottom"><div className="avatar">M</div><div><strong>MEGA account</strong><small>{account ? 'Session connected' : 'Awaiting connection'}</small></div><span className={'dot ' + (account ? 'green' : '')} /></div></aside>
    <div className="body"><header><span>Workspace <span className="slash">/</span> <strong>Import & rename</strong></span><div className="header-tools"><span className="local"><LockClosedIcon /> Your private workspace</span><ThemePicker />{authenticated && <Button variant="outline" className="sign-out" disabled={busy} onClick={signOut}>Sign out</Button>}</div></header>
      <main><div className="title-row"><div><h1>Prepare your files for compatibility with Debrid services.</h1><p>Import from MEGA, tidy up filenames, and share in one place.</p></div><span className="version">v1.0</span></div>
        <div className="stats"><div><small>COMPLETED IMPORTS</small><strong>{String(completed.length).padStart(2, '0')}<span> folders processed</span></strong></div><div><small>FILENAMES CLEANED</small><strong>{String(renamed).padStart(2, '0')}<span> originals preserved</span></strong></div><div><small>ACCOUNT STATUS</small><strong className="status-text"><span className={'dot ' + (account ? 'green' : '')} />{account ? 'Connected' : 'Disconnected'}<span>MEGAcmd</span></strong></div></div>
        {restoring && <p role="status" className="restore-session">Restoring workspace session…</p>}{error && <div role="alert" className="error">{error}</div>}
        {notice && <div role="status" className="notice">{notice}</div>}
        {authenticated && <section className="card storage-card" aria-label="Account storage"><div className="section-heading"><h2>Cloud storage</h2><Button variant="outline" disabled={busy || !account} onClick={() => setConfirmation({ kind: 'empty' })}><TrashIcon />Empty trash</Button></div>{storage ? <><div className="storage-metrics"><div><small>AVAILABLE</small><strong>{bytes(storage.availableBytes)}</strong></div><div><small>USED / TOTAL</small><strong>{bytes(storage.usedBytes)} <span>/ {bytes(storage.totalBytes)}</span></strong></div><div><small>IN TRASH</small><strong>{bytes(storage.trashBytes)}</strong></div></div><progress aria-label="Cloud storage used" max={Math.max(storage.totalBytes, 1)} value={Math.min(storage.usedBytes, storage.totalBytes)} /><p>Trash counts toward your limit. Storage checked at {new Date(storage.checkedAt).toLocaleTimeString()}.</p></> : <p>{storageError || (account ? 'Checking storage…' : 'Sign in to MEGAcmd to view cloud storage.')}</p>}</section>}
        {!authenticated && !restoring && <form className="connection" onSubmit={connect}><LockClosedIcon /><div><strong>Connect to your workspace</strong><small>Enter your API token once to remember this workspace for 30 days.</small></div><input aria-label="API token" type="password" placeholder="API token" value={draft} onChange={e => setDraft(e.target.value)} required /><Button disabled={busy}>Connect <ArrowRightIcon /></Button></form>}
        <div className="main-grid"><section className="card import-card" id="import"><div className="card-heading"><span className="icon-box"><Link2Icon /></span><div><h2>Import a MEGA link</h2><p>Your next clean folder starts here.</p></div><span className="badge">NEW IMPORT</span></div><form onSubmit={submit}><label htmlFor="mega-url">File or folder URL</label><div className="url-input"><Link2Icon /><input id="mega-url" type="url" placeholder="https://mega.nz/folder/…#…" value={url} disabled={busy} onChange={e => { setUrl(e.target.value); setCapacityCheck(null); }} required /></div><div className="size-check-row"><small className="hint">Include the full link with its decryption key.</small><Button type="button" variant="outline" disabled={!authenticated || !account || busy || !url.trim()} onClick={inspectLink}>Check size</Button></div>{capacityCheck && <div role="status" className={'capacity-result ' + (capacityCheck.fits ? 'fits' : 'over-limit')}><strong>{capacityCheck.fits ? 'This import fits the current available space.' : 'This import exceeds the available space.'}</strong><p>{bytes(capacityCheck.sourceBytes)} of files + {bytes(capacityCheck.reserveBytes)} report reserve · {bytes(capacityCheck.availableBytes)} available</p>{!capacityCheck.fits && <p>Free at least {bytes(capacityCheck.shortfallBytes)} before importing.</p>}</div>}<div className="steps"><div><CheckIcon /><span>Import into your connected MEGA account</span></div><div><CheckIcon /><span>Strip matching tags and rename files</span></div><div><CheckIcon /><span>Save original names in a .txt manifest</span></div><div><CheckIcon /><span>Generate a shareable link for every file</span></div></div><Button className="submit" disabled={!authenticated || !account || busy}><LightningBoltIcon />{busy ? 'Working…' : 'Import & rename'}<ArrowRightIcon /></Button><div className="footnote"><LockClosedIcon />Space is checked again before import. Files stay in MEGA.</div></form></section>
          <RulesEditor api={api} connected={authenticated} /></div>
        <section className="card activity" id="activity"><div className="section-heading"><div><h2>Recent imports</h2><p>Your files, with a little less clutter.</p></div><div className="history-heading-actions"><span className="badge muted">{jobs.length} IMPORTS</span>{authenticated && <Button variant="outline" disabled={busy || !jobs.length} onClick={() => setConfirmation({kind: 'clear-history'})}><TrashIcon />Clear history</Button>}</div></div>{!jobs.length ? <div className="empty"><span className="empty-icon"><FileTextIcon /></span><h3>Nothing here ヽ(ー_ー )ノ</h3><p>Import your first link to see filenames and shareable URLs.</p></div> : <><div className="job-list">{jobs.map(j => <button key={j.id} className={'job ' + (selected?.id === j.id ? 'selected' : '')} onClick={() => setActive(j.id)}><FileTextIcon /><span><strong>Import {j.id.slice(0, 8)}</strong><small>{j.files.length} files · {j.status}</small></span><span className={'state ' + j.status}>{j.status === 'complete' ? <CheckIcon /> : j.status === 'failed' ? 'Failed' : ['trashed', 'deleted'].includes(j.status) ? j.status : j.progress + '%'}</span></button>)}</div>{selected && <div className="results"><div className="result-header"><strong>Import {selected.id.slice(0, 8)}</strong>{selected.files.some(f => f.url) && <Button variant="outline" onClick={copy}>{copied ? <CheckIcon /> : <CopyIcon />}{copied ? 'Copied' : 'Copy links'}</Button>}</div>{!terminal.includes(selected.status) && <><progress max="100" value={selected.progress} /><p role="status">{selected.status} · {selected.progress}%</p></>}<div className="import-actions">{terminal.includes(selected.status) && <Button variant="outline" disabled={busy} onClick={() => setConfirmation({kind: 'remove-history', id: selected.id})}><TrashIcon />Remove from history</Button>}{['complete', 'failed'].includes(selected.status) && selected.importCreated !== false && <Button variant="outline" disabled={busy} onClick={() => setConfirmation({ kind: 'trash', id: selected.id })}><TrashIcon />Trash import</Button>}{['complete', 'failed', 'trashed'].includes(selected.status) && selected.importCreated !== false && <Button className="danger" disabled={busy} onClick={() => setConfirmation({ kind: 'trash-empty', id: selected.id })}><TrashIcon />{selected.status === 'trashed' ? 'Empty account trash' : 'Trash & empty trash'}</Button>}</div><JobDiagnostics job={selected} />{selected.files.map((f, i) => <div className="file-row" key={i}><FileTextIcon /><div><strong>{f.renamed.split('/').pop()}</strong><small>Original: {f.original.split('/').pop()}</small>{f.matches.length > 0 && <small>Removed: {f.matches.join(', ')}</small>}</div>{f.url && <a href={f.url} target="_blank" rel="noreferrer" aria-label={'Open ' + f.renamed}><ExternalLinkIcon /></a>}</div>)}<div className="result-links">{selected.manifestUrl && <a href={selected.manifestUrl} target="_blank" rel="noreferrer"><FileTextIcon />Original filename report <ExternalLinkIcon /></a>}{selected.folderUrl && <a href={selected.folderUrl} target="_blank" rel="noreferrer">Open imported folder <ExternalLinkIcon /></a>}</div></div>}</>}</section>
        {confirmation && <ConfirmAction action={confirmation} busy={busy} onCancel={() => setConfirmation(null)} onConfirm={manage} />}<footer><span><span className="brand-mini">m↗</span></span><span>Powered by MEGAcmd <span className="dot green" /></span></footer></main></div></div>;
}
createRoot(document.getElementById('root')).render(<App />);
